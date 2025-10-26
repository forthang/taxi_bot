module.exports = {
  apps: [{
    name: 'дмитрий',
    script: 'bot.py',
    interpreter: '/opt/blacktaxi/telegram-vip-bot/venv/bin/python3',
    cwd: '/opt/blacktaxi/telegram-vip-bot',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      NODE_ENV: 'production'
    },
    error_file: './logs/err.log',
    out_file: './logs/out.log',
    log_file: './logs/combined.log',
    time: true
  }, {
    name: 'дмитрий-админ',
    script: 'admin_panel.py',
    interpreter: '/opt/blacktaxi/telegram-vip-bot/venv/bin/python3',
    cwd: '/opt/blacktaxi/telegram-vip-bot',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '512M',
    env: {
      NODE_ENV: 'production'
    },
    error_file: './logs/admin-err.log',
    out_file: './logs/admin-out.log',
    log_file: './logs/admin-combined.log',
    time: true
  }]
}