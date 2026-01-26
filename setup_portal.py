from flask import Flask, request, render_template_string
import subprocess
import os
import time

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>VECTOR Setup</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #000; color: #ff8c00; font-family: sans-serif; text-align: center; padding: 20px; }
        input { padding: 15px; margin: 10px 0; width: 85%; border: 1px solid #333; background: #111; color: #fff; border-radius: 5px; font-size: 16px; }
        button { background: #ff8c00; border: none; padding: 15px; width: 90%; font-weight: bold; cursor: pointer; border-radius: 5px; margin-top: 10px; }
        .status { margin: 20px; padding: 10px; border-radius: 5px; display: none; }
    </style>
</head>
<body>
    <h1 style="letter-spacing: 5px;">VECTOR OS</h1>
    <p>НАСТРОЙКА СЕТИ</p>
    <form method="POST">
        <input type="text" name="ssid" placeholder="Название Wi-Fi (SSID)" required spellcheck="false"><br>
        <input type="password" name="password" placeholder="Пароль" required><br>
        <button type="submit">ПОДКЛЮЧИТЬ</button>
    </form>
    <p style="font-size: 12px; color: #555; mt: 20px;">Убедитесь, что зеркало находится в зоне действия роутера.</p>
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        ssid = request.form['ssid'].strip()
        pw = request.form['password'].strip()
        
        print(f"Попытка подключения к {ssid}...")
        
        # 1. Сначала пробуем просто пересканировать
        subprocess.run('nmcli device wifi rescan', shell=True)
        time.sleep(3)
        
        # 2. Попытка подключения
        # Добавляем --wait 10, чтобы nmcli дольше искал сеть перед тем как сдаться
        cmd = f'nmcli --wait 15 device wifi connect "{ssid}" password "{pw}"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if res.returncode == 0:
            # Успех: создаем файл-флаг
            flag_path = "/home/yerniyaz/Desktop/vector/.first_run_completed"
            with open(flag_path, "w") as f:
                f.write("done")
            return "<h1>УСПЕШНО!</h1><p>Зеркало подключается. Подождите 10 секунд...</p>"
        else:
            # Если не нашел, пробуем принудительно через 'nmcli d wifi connect' еще раз
            # Иногда помогает указать интерфейс явно
            print(f"Первая попытка не удалась: {res.stderr}")
            return f"<h1>ОШИБКА</h1><p>Сеть '{ssid}' не найдена или пароль неверный. Попробуйте еще раз, убедившись в правильности имени (регистр важен!)</p><a href='/' style='color:orange'>НАЗАД</a>"
            
    return render_template_string(HTML)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)