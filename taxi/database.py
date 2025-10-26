import json
from datetime import datetime, timedelta

from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import create_engine, update
from sqlalchemy import Column, Integer, String, Float, JSON, Boolean, DATE, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.orm import sessionmaker
from sqlalchemy import or_
import pytz

timezone = pytz.timezone("Europe/Moscow")

# Создаем движок для SQLite
engine = create_engine('sqlite:///database.db', pool_pre_ping=True)
Base = declarative_base()
Session = sessionmaker(bind=engine)
session = Session()

class Users(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    user_id = Column(String)  # Телеграм id юзера
    user_name = Column(String) # Телеграм имя юзера
    date_end_product = Column(DATE) # Дата окончания подписки
    notif = Column(String)  # Хранится округ по которому приходят уведомления иначе stop
    type_product = Column(String) # Тип подписки
    id_pay = Column(String) # Будем хранить идентификатор платежа. Отправлять запрос и смотреть статус


Base.metadata.create_all(engine)

# Добавляем юзера который нажал старт
def write_user(user_id, user_name):
    with Session() as session:
        user = session.query(Users).filter_by(user_id=user_id).first()
        if not user:
            new_user = Users(user_id=user_id, user_name=user_name)
            session.add(new_user)
            session.commit()
            print(f"Новый юзер записан в БД")

#  Подключение тестовой подписки
# Проверка значения в date_end_product. Если "None" то подключаем тест. Если любое другое, то отказ
def get_test_product(user_id):
    current_date = datetime.now(timezone)
    new_date = current_date + timedelta(days=3)
    with Session() as session:
        user = session.query(Users).filter_by(user_id=user_id).first()
        if user.date_end_product is None:
            user.date_end_product = new_date
            user.type_product = "Тестовый период"
            session.commit()
            return new_date.strftime("%d.%m.%Y")
        else:
            return False

# Записываем 31 день юзеру оплатившему Вип
def vip_product(user_id):
    with Session() as session:
        current_date = datetime.now(timezone)
        #new_date_vip = current_date + timedelta(days=31) # Плюс 31 день к текущей дате
        user = session.query(Users).filter_by(user_id=user_id).first()
        if user.date_end_product:
            if current_date.date() < user.date_end_product:
                new_date_vip = user.date_end_product + timedelta(days=31)
                user.date_end_product = new_date_vip
                user.type_product = "VIP"
                session.commit()
                return new_date_vip.strftime("%d.%m.%Y")
            else:
                user.date_end_product = current_date.date() + timedelta(days=31)  # Записываем +30 дней к текущему
                user.type_product = "VIP"
                session.commit()
                return user.date_end_product.strftime("%d.%m.%Y")
        else:
            user.date_end_product = current_date.date() + timedelta(days=31) # Записываем +30 дней к текущему
            user.type_product = "VIP"
            session.commit()
            return user.date_end_product.strftime("%d.%m.%Y")


# Продлеваем VIP на определенную кол. дней определенному юзеру
def vip_one(username, date):
    with Session() as session:
        current_date = datetime.now(timezone)
        #new_date_vip = current_date + timedelta(days=31) # Плюс 31 день к текущей дате
        user = session.query(Users).filter_by(user_name=username).first()
        if user:
            if user.type_product:
                if current_date.date() < user.date_end_product:
                    new_date_vip = user.date_end_product + timedelta(days=int(date))
                    user.date_end_product = new_date_vip
                    user.type_product = "VIP"
                    session.commit()
                    return f"Продлено до: {new_date_vip.strftime("%d.%m.%Y")}"
                else:
                    new_date_vip = current_date.date() + timedelta(days=int(date))
                    user.date_end_product = new_date_vip
                    user.type_product = "VIP"
                    session.commit()
                    return f"Продлено до: {new_date_vip.strftime("%d.%m.%Y")}"
            else:
                new_date_vip = current_date.date() + timedelta(days=int(date))
                user.date_end_product = new_date_vip
                user.type_product = "VIP"
                session.commit()
                return f"Продлено до: {new_date_vip.strftime("%d.%m.%Y")}"
        else:
            return ("Пользователя с таким юзернеймом нет в Базе\n"
                    "Попросите его стартануть бота и попробуйте еще раз.\n"
                    "Или перепроверьте юзернейм")

#  Продлеваем VIP всем пользователям на количество дней
def vip_all_date(time):
    with Session() as session:
        users = session.query(Users).all()
        for user in users:
            if user.type_product and "VIP" in user.type_product:
                user.date_end_product += timedelta(days=time)
                user.type_product = "VIP"
        session.commit()



# Продлеваем тестовый период всем пользователям на количество дней. Кроме VIP и PREMIUM
def test_all_date(time):
    with Session() as session:
        users = session.query(Users).all()
        for user in users:
            if user.type_product and not "VIP" in str(user.type_product)\
                    and not "PREMIUM" in str(user.type_product):
                    user.date_end_product += timedelta(days=time)
                    user.type_product = "Тестовый период"
            elif not user.date_end_product:
                current_date = datetime.now(timezone)
                user.date_end_product = current_date.date() + timedelta(days=time)
                user.type_product = "Тестовый период"
        session.commit()
        return True



#  Получаем статистику из БД
def all_state():
    with Session() as session:
        all_users = session.query(Users).count()
        vip_users = session.query(Users).filter(Users.type_product.like("%VIP%")).count()
        premium_users = session.query(Users).filter(Users.type_product.like("%PREMIUM%")).count()
        test_users = session.query(Users).filter(Users.type_product.like("%Тестовый период%")).count()
        return all_users, vip_users, premium_users, test_users


# Возвращаем данные об окончании подписки
def date_product(user_id):
    current_date = datetime.now(timezone)
    with Session() as session:
        user = session.query(Users).filter_by(user_id=user_id).first()
        date_test_product = user.date_end_product
        if date_test_product < current_date.date():
            return f"Ваш <b>{user.type_product}</b>  кончился: <b>{date_test_product.strftime("%d.%m.%Y")}</b>"
        elif date_test_product == current_date.date():
            return f"Ваш <b>{user.type_product}</b> кончается: <b>❗️❗️{date_test_product.strftime("%d.%m.%Y")}❗️❗️</b>"
        else:
            return f"Ваш <b>{user.type_product}</b> кончается: <b>️{date_test_product.strftime("%d.%m.%Y")}</b>"


# Запрашиваем дату окончания подписки и возвращаем False если просрочен или нету
# Try если не кончилась
def date_product_end(user_id):
    current_date = datetime.now(timezone)
    with Session() as session:
        user = session.query(Users).filter_by(user_id=user_id).first()
        if user:
            date_product = user.date_end_product
            if date_product:
                if date_product < current_date.date():
                    return False #  Если срок кончился
                else:
                    return True # Если есть подписка
            else:
                return False # Если еще нет подписки
        else:
            return False

# Запршиваем тип продукта юзера
def get_type_product(user_id):
    with Session() as session:
        user = session.query(Users).filter_by(user_id=user_id).first()
        return user.type_product


#  Удаляем юзера, который заблокировал бота
def del_user(user_id):
    with Session() as session:
        user = session.query(Users).filter_by(user_id=user_id).first()
        session.delete(user)
        session.commit()
        return user_id


# Устанавливаем уведомления в notif
def add_notif(user_id, city):
    with Session() as session:
        user = session.query(Users).filter_by(user_id=user_id).first()
        user.notif = city
        session.commit()
        print(f"Город: {city}")

# Ищем по городу юзера который установил уведомления
def get_notif_user_city(city):
    user = session.query(Users).filter_by(notif=city).first()
    if user:
        return user.user_id
    else:
        return False


def all_get_users(): #  Запрос всех юзеров
    users = session.query(Users).all()
    return users


#----------Работа с подписками, хранение идентификаторов и назначение статуса и срока подписки------------
# Записываем id платежа когда юзер нажмет оплатить
def write_id_pay(user_id, id_pay):
    user = session.query(Users).filter_by(user_id=user_id).first()
    if user.id_pay:
        res = user.id_pay
        print(type(res))
        user.id_pay += f" {id_pay}"
        session.commit()
        print("Идентификатор оплаты сохранен")
    else:
        res = user.id_pay
        print(type(res))
        user.id_pay = id_pay
        session.commit()
        print("Идентификатор оплаты сохранен2")

# Обнуление всех дат всех подписок
def null_date_product():
    with Session() as session:
        # Обновляем поле date_end_product на NULL для всех записей
        reset_date_end_product = update(Users).values(date_end_product=None)
        reset_type_product = update(Users).values(type_product=None)
        reset_id_pay = update(Users).values(id_pay=None)
        session.execute(reset_date_end_product)
        session.execute(reset_type_product)
        session.execute(reset_id_pay)
        session.commit()
        return True

# Получаем все идентификаторы оплаты юзера
def get_id_pay(user_id):
    with Session() as session:
        user_data = session.query(Users).filter_by(user_id=user_id).first()
        return user_data.id_pay

# Удаляем все id_pay после успешного подтверждения оплаты
def del_ids_pay(user_id):
    with Session() as session:
        user_data = session.query(Users).filter_by(user_id=user_id).first()
        print(user_data.user_name)
        user_data.id_pay = None
        session.commit()

# 5896017718

#  Удаляем все идетификаторы оплаты | Чистка
def del_ids():
    with Session() as session:
        user_data = session.query(Users).all()
        for user in user_data:
            user.id_pay = None
            session.commit()


