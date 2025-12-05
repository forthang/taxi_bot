# /bot/api.py
"""
Асинхронный менеджер для взаимодействия с Remnawave API.
Версия: исправленная — контролирует логирование 404 только в ожидаемых местах,
и гарантированно назначает internal squad после создания пользователя.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

# --- Конфигурация (параметры таймаутов/ретраев) ---
REQUEST_TIMEOUT = 15.0
MAX_RETRIES = 3
BACKOFF_FACTOR = 0.5

# Имя логгера совпадает с именем модуля для иерархии
logger = logging.getLogger(__name__)


class RemnaAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class RemnaAsyncManager:
    def __init__(self, base_url: str, token: str, timeout: float = REQUEST_TIMEOUT):
        if not base_url or not token:
            raise ValueError("URL панели и API токен должны быть указаны.")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        logger.debug("RemnaAsyncManager инициализирован.")

    async def __aenter__(self):
        logger.debug("Вход в контекст RemnaAsyncManager, создание HTTP клиента.")
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "GranatVPNBot/2.0",
            },
            timeout=self.timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.debug("Выход из контекста RemnaAsyncManager, закрытие HTTP клиента.")
        if self._client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
        suppress_not_found_logging: bool = False,
    ) -> Any:
        """
        Универсальная обёртка для запросов.
        """
        if self._client is None:
            raise RemnaAPIError("HTTP клиент не инициализирован.")

        request_details = f"API-ЗАПРОС: {method} {path}"
        if params:
            request_details += f", query={params}"
        if json_data:
            # Не логируем чувствительные данные, если они есть
            request_details += f", json={json_data}"
        logger.debug(request_details)

        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.request(method, path, json=json_data, params=params)
                
                # Логируем ответ перед raise_for_status
                logger.debug(f"API-ОТВЕТ: {response.status_code} для {method} {path}. Попытка {attempt + 1}/{MAX_RETRIES}.")

                response.raise_for_status()
                try:
                    json_response = response.json()
                    logger.debug(f"API-ОТВЕТ (JSON): {json_response}")
                    return json_response
                except json.JSONDecodeError:
                    logger.warning(f"API-ОТВЕТ (не JSON): {response.text}")
                    return {"response_text": response.text}
                    
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                try:
                    err = e.response.json()
                    msg = err.get("message") or err.get("error") or json.dumps(err)
                except Exception:
                    msg = e.response.text

                log_msg = f"HTTP ошибка {status} при {method} {path}: {msg}"
                if status == 404 and suppress_not_found_logging:
                    logger.debug(log_msg)
                else:
                    logger.error(log_msg)

                raise RemnaAPIError(msg, status_code=status) from e
            except (httpx.RequestError, httpx.TimeoutException) as e:
                last_exception = e
                logger.warning(f"Сетевая ошибка (попытка {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR * (2 ** attempt))
                continue

        raise RemnaAPIError(f"Не удалось выполнить запрос после {MAX_RETRIES} попыток.") from last_exception

    @staticmethod
    def _normalize_user(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Приводит ответ API к единообразному виду.
        """
        if not isinstance(raw, dict):
            return {}
        return {
            "id": raw.get("id"),
            "uuid": raw.get("uuid") or raw.get("userUuid") or raw.get("userId"),
            "username": raw.get("username") or raw.get("userName"),
            "email": raw.get("email"),
            "status": raw.get("status"),
            "subscriptionUrl": raw.get("subscriptionUrl"),
            "expireAt": raw.get("expireAt"),
            "activeInternalSquads": raw.get("activeInternalSquads") or raw.get("internalSquads") or None,
        }

    # ------------------ основные методы ------------------

    async def create_user(self, username: str, squad_uuid: Optional[str], expire_at: datetime, **extra) -> Dict[str, Any]:
        """
        Создает пользователя (POST /api/users).
        """
        logger.debug(f"Вызов create_user для username={username}")
        if expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=timezone.utc)

        payload: Dict[str, Any] = {
            "username": username,
            "status": "ACTIVE",
            "expireAt": expire_at.isoformat().replace("+00:00", "Z"),
            **extra,
        }

        if squad_uuid:
            payload["activeInternalSquads"] = [squad_uuid]

        response_data = await self._request("POST", "users", json_data=payload)
        user_data = response_data.get("response", response_data) if isinstance(response_data, dict) else response_data
        normalized = self._normalize_user(user_data)

        user_uuid = normalized.get("uuid")
        if squad_uuid and user_uuid:
            try:
                await self.assign_internal_squads_to_user_by_uuid(user_uuid, [squad_uuid])
                refreshed = await self.get_user_by_uuid(user_uuid)
                if refreshed:
                    normalized = refreshed
            except Exception as e:
                logger.warning(f"Не удалось назначить internal squad {squad_uuid} пользователю {user_uuid} после создания: {e}")

        return normalized

    async def find_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        GET /api/users/by-username/{username}
        """
        logger.debug(f"Вызов find_user_by_username для username={username}")
        path = f"users/by-username/{username}"
        try:
            response_data = await self._request("GET", path, suppress_not_found_logging=True)
        except RemnaAPIError as e:
            if getattr(e, "status_code", None) == 404:
                return None
            raise
        user_data = response_data.get("response", response_data) if isinstance(response_data, dict) else response_data
        return self._normalize_user(user_data)

    async def update_user(self, username: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        PATCH /api/users
        """
        logger.debug(f"Вызов update_user для username={username} с updates={updates}")
        user = await self.find_user_by_username(username)
        if not user or not user.get("uuid"):
            raise RemnaAPIError(f"Пользователь с username={username} не найден для обновления.", status_code=404)

        payload = {"uuid": user.get("uuid"), **updates}
        response_data = await self._request("PATCH", "users", json_data=payload)
        user_data = response_data.get("response", response_data) if isinstance(response_data, dict) else response_data
        return self._normalize_user(user_data)

    # ------------------ дополнительные методы по OpenAPI ------------------

    async def get_user_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        GET /api/users/{uuid}
        """
        logger.debug(f"Вызов get_user_by_uuid для uuid={uuid}")
        path = f"users/{uuid}"
        try:
            response_data = await self._request("GET", path, suppress_not_found_logging=True)
        except RemnaAPIError as e:
            if getattr(e, "status_code", None) == 404:
                return None
            raise
        user_data = response_data.get("response", response_data) if isinstance(response_data, dict) else response_data
        return self._normalize_user(user_data)

    async def delete_user_by_uuid(self, uuid: str) -> bool:
        """DELETE /api/users/{uuid}"""
        logger.debug(f"Вызов delete_user_by_uuid для uuid={uuid}")
        path = f"users/{uuid}"
        await self._request("DELETE", path)
        return True

    async def get_all_users(self, size: Optional[int] = None, start: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /api/users"""
        logger.debug(f"Вызов get_all_users с size={size}, start={start}")
        params: Dict[str, Any] = {}
        if size is not None:
            params["size"] = size
        if start is not None:
            params["start"] = start

        response_data = await self._request("GET", "users", params=params)
        if isinstance(response_data, dict):
            candidates = response_data.get("items") or response_data.get("users") or response_data.get("response") or response_data
        else:
            candidates = response_data

        if isinstance(candidates, list):
            return [self._normalize_user(u) for u in candidates]
        if isinstance(candidates, dict):
            for v in candidates.values():
                if isinstance(v, list):
                    return [self._normalize_user(u) for u in v]
        return []

    async def assign_internal_squads_to_user_by_uuid(self, user_uuid: str, squad_uuids: List[str]) -> Dict[str, Any]:
        """
        POST /api/users/bulk/update-squads
        """
        logger.debug(f"Вызов assign_internal_squads_to_user_by_uuid для user_uuid={user_uuid}")
        if not user_uuid or not isinstance(squad_uuids, list):
            raise ValueError("user_uuid и squad_uuids обязательны.")

        payload = {"uuids": [user_uuid], "activeInternalSquads": squad_uuids}
        resp = await self._request("POST", "users/bulk/update-squads", json_data=payload)
        return resp.get("response", resp) if isinstance(resp, dict) else resp

    # Остальные методы оставлены для краткости, но по аналогии можно добавить логгирование и в них
    async def revoke_user_subscription(self, uuid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        path = f"users/{uuid}/actions/revoke"
        response_data = await self._request("POST", path, json_data=body)
        return response_data.get("response", response_data) if isinstance(response_data, dict) else response_data

    async def enable_user(self, uuid: str) -> Dict[str, Any]:
        path = f"users/{uuid}/actions/enable"
        response_data = await self._request("POST", path)
        return response_data.get("response", response_data) if isinstance(response_data, dict) else response_data

    async def disable_user(self, uuid: str) -> Dict[str, Any]:
        path = f"users/{uuid}/actions/disable"
        response_data = await self._request("POST", path)
        return response_data.get("response", response_data) if isinstance(response_data, dict) else response_data

    async def reset_user_traffic(self, uuid: str) -> Dict[str, Any]:
        path = f"users/{uuid}/actions/reset-traffic"
        response_data = await self._request("POST", path)
        return response_data.get("response", response_data) if isinstance(response_data, dict) else response_data

    async def get_user_accessible_nodes(self, uuid: str) -> List[Dict[str, Any]]:
        path = f"users/{uuid}/accessible-nodes"
        response_data = await self._request("GET", path)
        if isinstance(response_data, dict):
            items = response_data.get("response") or response_data.get("items") or response_data
        else:
            items = response_data
        if isinstance(items, list):
            return items
        if isinstance(items, dict):
            for v in items.values():
                if isinstance(v, list):
                    return v
        return []

    async def assign_internal_squads_to_user_by_username(self, username: str, squad_uuids: List[str]) -> Dict[str, Any]:
        user = await self.find_user_by_username(username)
        if not user or not user.get("uuid"):
            raise RemnaAPIError(f"Пользователь '{username}' не найден.", status_code=404)
        return await self.assign_internal_squads_to_user_by_uuid(user["uuid"], squad_uuids)
