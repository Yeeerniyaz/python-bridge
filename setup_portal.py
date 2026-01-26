from flask import Flask, request, render_template_string
import subprocess
import os
import time

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head><title>VECTOR Setup</title><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="background: #000; color: orange; font-family: sans-serif; text-align: center; padding: 50px;">
    <h1>VECTOR OS</h1>
    <p>Введите данные Wi-Fi</p>
    <form method="POST">
        <input type="text" name="ssid" placeholder="Название Wi-Fi" required style="padding: 10px; margin: 5px;"><br>
        <input type="password" name="password" placeholder="Пароль" required style="padding: 10px; margin: 5px;"><br>
        <button type="submit" style="background: orange; border: none; padding: 10px 20px; margin-top: 10px;">ПОДКЛЮЧИТЬ</button>
    </form>
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        ssid = request.form['ssid']
        pw = request.form['password']
        
        # Пытаемся подключиться к сети
        cmd = f'nmcli device wifi connect "{ssid}" password "{pw}"'
        res = subprocess.run(cmd, shell=True)
        
        if res.returncode == 0:
            # Если успешно — создаем метку первого запуска
            with open("/home/yerniyaz/Desktop/vector/.first_run_completed", "w") as f:
                f.write("done")
            return "<h1>Успешно! Зеркало запускается...</h1><script>setTimeout(() => window.close(), 3000)</script>"
        else:
            return "<h1>Ошибка! Проверьте пароль и попробуйте снова.</h1><a href='/'>Назад</a>"
            
    return render_template_string(HTML)

if __name__ == '__main__':
    # Запускаем на порту 8080 (или 80, если есть права sudo)
    app.run(host='0.0.0.0', port=8080)