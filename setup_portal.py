from flask import Flask, request, render_template_string
import subprocess
import os
import time

app = Flask(__name__)

# Красивый и понятный интерфейс
HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>VECTOR Setup</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #000; color: #ff8c00; font-family: sans-serif; text-align: center; padding: 20px; }
        input { padding: 15px; margin: 10px 0; width: 80%; border: 1px solid #333; background: #111; color: #fff; border-radius: 5px; }
        button { background: #ff8c00; border: none; padding: 15px; width: 85%; font-weight: bold; cursor: pointer; border-radius: 5px; }
        .info { color: #555; font-size: 12px; margin-top: 20px; }
    </style>
</head>
<body>
    <h1 style="letter-spacing: 5px;">VECTOR OS</h1>
    <p>НАСТРОЙКА WI-FI</p>
    <form method="POST">
        <input type="text" name="ssid" placeholder="Название сети (SSID)" required spellcheck="false"><br>
        <input type="password" name="password" placeholder="Пароль" required><br>
        <button type="submit">ПОДКЛЮЧИТЬ ЗЕРКАЛО</button>
    </form>
    <p class="info">Убедитесь, что название сети введено точно (с учетом регистра)</p>
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        ssid = request.form['ssid'].strip()
        pw = request.form['password'].strip()
        
        # 1. Заставляем малинку обновить список доступных сетей
        subprocess.run('nmcli device wifi rescan', shell=True)
        time.sleep(2) 
        
        # 2. Пытаемся подключиться
        # Используем --ask на случай странных символов в SSID
        cmd = f'nmcli device wifi connect "{ssid}" password "{pw}"'
        print(f"Попытка подключения к: {ssid}")
        
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if res.returncode == 0:
            # Создаем метку завершения первого запуска
            flag_path = "/home/yerniyaz/Desktop/vector/.first_run_completed"
            with open(flag_path, "w") as f:
                f.write("done")
            
            return f"<h1>УСПЕШНО!</h1><p>Зеркало подключено к {ssid}. Оно запустится через несколько секунд.</p>"
        else:
            # Если ошибка — выводим её, чтобы понять причину
            error_msg = res.stderr if res.stderr else "Сеть не найдена или пароль неверный"
            return f"<h1>ОШИБКА</h1><p>{error_msg}</p><a href='/' style='color:orange'>Попробовать снова</a>"
            
    return render_template_string(HTML)

if __name__ == '__main__':
    # Слушаем на всех интерфейсах на порту 8080
    app.run(host='0.0.0.0', port=8080, debug=False)