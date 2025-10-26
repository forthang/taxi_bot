import os
import sqlite3
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('ADMIN_SECRET_KEY', 'your-secret-key-here')

# Настройки админа
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class AdminUser(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return AdminUser(user_id)

def get_db_connection():
    conn = sqlite3.connect('bot.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
@login_required
def dashboard():
    conn = get_db_connection()
    
    # Статистика
    total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    vip_users = conn.execute('SELECT COUNT(*) FROM users WHERE is_vip = 1').fetchone()[0]
    total_payments = conn.execute('SELECT COUNT(*) FROM payments').fetchone()[0]
    successful_payments = conn.execute('SELECT COUNT(*) FROM payments WHERE status = "CONFIRMED"').fetchone()[0]
    total_taxi_orders = conn.execute('SELECT COUNT(*) FROM taxi_orders WHERE is_valid = 1').fetchone()[0]
    active_taxi_orders = conn.execute('SELECT COUNT(*) FROM taxi_orders WHERE is_valid = 1 AND status = "active"').fetchone()[0]
    
    # Последние пользователи
    recent_users = conn.execute('''
        SELECT user_id, username, is_vip, vip_until, created_at 
        FROM users 
        ORDER BY created_at DESC 
        LIMIT 10
    ''').fetchall()
    
    # Последние платежи
    recent_payments = conn.execute('''
        SELECT p.payment_id, p.user_id, p.amount, p.status, p.created_at, u.username
        FROM payments p
        LEFT JOIN users u ON p.user_id = u.user_id
        ORDER BY p.created_at DESC 
        LIMIT 10
    ''').fetchall()
    
    conn.close()
    
    return render_template('dashboard.html',
                         total_users=total_users,
                         vip_users=vip_users,
                         total_payments=total_payments,
                         successful_payments=successful_payments,
                         total_taxi_orders=total_taxi_orders,
                         active_taxi_orders=active_taxi_orders,
                         recent_users=recent_users,
                         recent_payments=recent_payments)

@app.route('/users')
@login_required
def users():
    conn = get_db_connection()
    
    # Фильтры
    search = request.args.get('search', '')
    vip_filter = request.args.get('vip', '')
    page = int(request.args.get('page', 1))
    per_page = 20
    
    # Базовый запрос
    query = '''
        SELECT user_id, username, is_vip, vip_until, created_at,
               (SELECT COUNT(*) FROM payments WHERE user_id = users.user_id) as payments_count,
               (SELECT SUM(amount) FROM payments WHERE user_id = users.user_id AND status = 'CONFIRMED') as total_spent
        FROM users
        WHERE 1=1
    '''
    params = []
    
    if search:
        query += ' AND (username LIKE ? OR user_id LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    if vip_filter == 'vip':
        query += ' AND is_vip = 1'
    elif vip_filter == 'non_vip':
        query += ' AND is_vip = 0'
    
    # Общее количество
    count_query = f'SELECT COUNT(*) FROM ({query})'
    total = conn.execute(count_query, params).fetchone()[0]
    
    # Пагинация
    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([per_page, (page - 1) * per_page])
    
    users_list = conn.execute(query, params).fetchall()
    conn.close()
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('users.html',
                         users=users_list,
                         search=search,
                         vip_filter=vip_filter,
                         page=page,
                         total_pages=total_pages,
                         total=total)

@app.route('/payments')
@login_required
def payments():
    conn = get_db_connection()
    
    # Фильтры
    status_filter = request.args.get('status', '')
    page = int(request.args.get('page', 1))
    per_page = 20
    
    query = '''
        SELECT p.payment_id, p.user_id, p.amount, p.status, p.created_at, u.username
        FROM payments p
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE 1=1
    '''
    params = []
    
    if status_filter:
        query += ' AND p.status = ?'
        params.append(status_filter)
    
    # Общее количество
    count_query = f'SELECT COUNT(*) FROM ({query})'
    total = conn.execute(count_query, params).fetchone()[0]
    
    # Пагинация
    query += ' ORDER BY p.created_at DESC LIMIT ? OFFSET ?'
    params.extend([per_page, (page - 1) * per_page])
    
    payments_list = conn.execute(query, params).fetchall()
    conn.close()
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('payments.html',
                         payments=payments_list,
                         status_filter=status_filter,
                         page=page,
                         total_pages=total_pages,
                         total=total)

@app.route('/taxi_orders')
@login_required
def taxi_orders():
    # Получаем API ключ Яндекс Карт
    yandex_api_key = os.getenv('YANDEX_MAPS_API_KEY', 'ваш_яндекс_ключ')
    conn = get_db_connection()
    
    # Фильтры
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    page = int(request.args.get('page', 1))
    per_page = 20
    
    query = '''
        SELECT * FROM taxi_orders
        WHERE is_valid = 1
    '''
    params = []
    
    if search:
        query += ' AND (route LIKE ? OR contact LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    if status_filter:
        query += ' AND status = ?'
        params.append(status_filter)
    
    # Общее количество
    count_query = f'SELECT COUNT(*) FROM ({query})'
    total = conn.execute(count_query, params).fetchone()[0]
    
    # Пагинация
    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([per_page, (page - 1) * per_page])
    
    orders_list = conn.execute(query, params).fetchall()
    conn.close()
    
    # Преобразуем Row объекты в словари для JSON сериализации
    orders_dict = [dict(row) for row in orders_list]
    
    # Отладочная информация
    print(f"Debug: Found {len(orders_dict)} orders")
    print(f"Debug: Yandex API key: {yandex_api_key}")
    for i, order in enumerate(orders_dict[:2]):  # Показываем первые 2 заказа
        print(f"Debug: Order {i+1}: {order.get('route', 'No route')}")
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('taxi_orders.html',
                         orders=orders_dict,
                         search=search,
                         status_filter=status_filter,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         yandex_api_key=yandex_api_key)

@app.route('/api/user/<int:user_id>/toggle_vip', methods=['POST'])
@login_required
def toggle_vip(user_id):
    conn = get_db_connection()
    
    user = conn.execute('SELECT is_vip FROM users WHERE user_id = ?', (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'success': False, 'error': 'User not found'})
    
    new_vip_status = 0 if user['is_vip'] else 1
    vip_until = datetime.now() + timedelta(days=30) if new_vip_status else None
    
    conn.execute('''
        UPDATE users 
        SET is_vip = ?, vip_until = ? 
        WHERE user_id = ?
    ''', (new_vip_status, vip_until, user_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True, 
        'is_vip': new_vip_status,
        'vip_until': vip_until.isoformat() if vip_until else None
    })

@app.route('/api/user/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    conn = get_db_connection()
    
    # Удаляем пользователя и все его платежи
    conn.execute('DELETE FROM payments WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/stats')
@login_required
def get_stats():
    conn = get_db_connection()
    
    # Статистика по дням (последние 30 дней)
    stats = conn.execute('''
        SELECT 
            DATE(created_at) as date,
            COUNT(*) as new_users,
            SUM(CASE WHEN is_vip = 1 THEN 1 ELSE 0 END) as vip_users
        FROM users 
        WHERE created_at >= date('now', '-30 days')
        GROUP BY DATE(created_at)
        ORDER BY date
    ''').fetchall()
    
    # Статистика платежей
    payment_stats = conn.execute('''
        SELECT 
            DATE(created_at) as date,
            COUNT(*) as total_payments,
            SUM(CASE WHEN status = 'CONFIRMED' THEN 1 ELSE 0 END) as successful_payments,
            SUM(CASE WHEN status = 'CONFIRMED' THEN amount ELSE 0 END) as total_revenue
        FROM payments 
        WHERE created_at >= date('now', '-30 days')
        GROUP BY DATE(created_at)
        ORDER BY date
    ''').fetchall()
    
    conn.close()
    
    return jsonify({
        'user_stats': [dict(row) for row in stats],
        'payment_stats': [dict(row) for row in payment_stats]
    })

@app.route('/api/taxi_order/<int:order_id>')
@login_required
def get_taxi_order(order_id):
    conn = get_db_connection()
    
    order = conn.execute('SELECT * FROM taxi_orders WHERE id = ?', (order_id,)).fetchone()
    conn.close()
    
    if order:
        return jsonify({
            'success': True,
            'order': dict(order)
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Order not found'
        })

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            user = AdminUser(username)
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Неверные учетные данные')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/api/cancel_payment', methods=['POST'])
@login_required
def cancel_payment():
    """API для отмены платежа"""
    try:
        data = request.get_json()
        payment_id = data.get('payment_id')
        amount = data.get('amount')  # в копейках, опционально
        
        if not payment_id:
            return jsonify({'error': 'Payment ID is required'}), 400
        
        # Импортируем необходимые модули
        import asyncio
        import aiohttp
        import hashlib
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        
        # Создаем экземпляр TinkoffPayment
        class TinkoffPayment:
            def __init__(self):
                self.terminal_key = os.getenv('TINKOFF_TERMINAL_KEY')
                self.secret_key = os.getenv('TINKOFF_SECRET_KEY')
                self.api_url = 'https://securepay.tinkoff.ru/v2/'
            
            def generate_token(self, params):
                """Генерация токена для подписи запроса"""
                token_params = params.copy()
                token_params['Password'] = self.secret_key
                sorted_params = sorted(token_params.items())
                values = ''.join([str(v) for k, v in sorted_params if k not in ['Token', 'DATA', 'Receipt']])
                return hashlib.sha256(values.encode()).hexdigest()
            
            async def cancel_payment(self, payment_id, amount=None):
                """Отмена платежа"""
                params = {
                    'TerminalKey': self.terminal_key,
                    'PaymentId': payment_id
                }
                
                if amount is not None:
                    params['Amount'] = amount
                
                params['Token'] = self.generate_token(params)
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(f'{self.api_url}Cancel', json=params) as response:
                        result = await response.json()
                        return result.get('Success', False), result
        
        # Выполняем отмену платежа
        async def cancel_payment_async():
            tinkoff = TinkoffPayment()
            success, result = await tinkoff.cancel_payment(payment_id, amount)
            return success, result
        
        # Запускаем асинхронную функцию
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            success, result = loop.run_until_complete(cancel_payment_async())
        finally:
            loop.close()
        
        if success:
            # Обновляем статус в базе данных
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('UPDATE payments SET status = ? WHERE payment_id = ?', ('CANCELLED', payment_id))
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message': 'Платеж успешно отменен',
                'result': result
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Ошибка отмены платежа',
                'result': result
            }), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync_users', methods=['POST'])
@login_required
def sync_users():
    """API для синхронизации пользователей из группы"""
    try:
        import asyncio
        import aiohttp
        
        # Создаем функцию для получения участников группы
        async def get_group_members():
            bot_token = os.getenv('BOT_TOKEN')
            group_id = os.getenv('FREE_GROUP_ID')
            
            # Получаем количество участников
            url = f"https://api.telegram.org/bot{bot_token}/getChatMemberCount"
            params = {"chat_id": group_id}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    result = await response.json()
                    if result.get('ok'):
                        member_count = result['result']
                        print(f"Количество участников в группе: {member_count}")
                        
                        # Возвращаем только количество участников
                        return {"ok": True, "result": [], "member_count": member_count}
                    else:
                        return result
        
        # Запускаем асинхронную функцию
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(get_group_members())
        finally:
            loop.close()
        
        if result.get('ok') and result.get('result'):
            members = result['result']
            member_count = result.get('member_count', len(members))
            added_count = 0
            
            conn = get_db_connection()
            for member in members:
                user_id = member.get('id')
                username = member.get('username')
                
                # Проверяем, есть ли пользователь в базе
                existing = conn.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,)).fetchone()
                
                if not existing:
                    # Добавляем пользователя в базу
                    conn.execute('''
                        INSERT INTO users (user_id, username, is_vip, created_at) 
                        VALUES (?, ?, 0, datetime('now'))
                    ''', (user_id, username))
                    added_count += 1
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message': f'Информация о группе получена. В группе {member_count} участников.',
                'total_members': member_count,
                'added_count': added_count
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Ошибка получения участников группы',
                'error': result.get('description', 'Unknown error')
            }), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5008, debug=True) 