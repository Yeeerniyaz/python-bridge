from flask import Flask, request, render_template_string
import subprocess
import os
import time

app = Flask(__name__)

def get_wifi_list():
    # Принудительный рескан и получение списка
    subprocess.run('nmcli device wifi rescan', shell=True)
    time.sleep(2)
    cmd = "nmcli -t -f SSID,SIGNAL device wifi list | sort -u -t: -k1,1"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    networks = []
    for line in res.stdout.split('\n'):
        if line.strip() and ':' in line:
            ssid, signal = line.split(':')
            if ssid: # Игнорируем скрытые сети без имени
                networks.append({'ssid': ssid, 'signal': signal})
    return networks

@app.route('/', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        ssid = request.form['ssid'].strip()
        pw = request.form['password'].strip()
        
        print(f"Попытка подключения к {ssid}...")
        cmd = f'nmcli --wait 15 device wifi connect "{ssid}" password "{pw}"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if res.returncode == 0:
            flag_path = "/home/yerniyaz/Desktop/vector/.first_run_completed"
            with open(flag_path, "w") as f: f.write("done")
            return "<h1>УСПЕШНО!</h1><p>Зеркало подключается к сети...</p>"
        else:
            return f"<h1>ОШИБКА</h1><p>{res.stderr}</p><a href='/'>НАЗАД</a>"

    # GET запрос: показываем список сетей
    networks = get_wifi_list()
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>VECTOR Setup</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { background: #000; color: #ff8c00; font-family: sans-serif; text-align: center; padding: 20px; }
            .net-item { background: #111; border: 1px solid #333; padding: 15px; margin: 10px 0; border-radius: 8px; cursor: pointer; display: flex; justify-content: space-between; }
            .net-item:hover { border-color: #ff8c00; }
            input { padding: 15px; margin: 10px 0; width: 85%; border: 1px solid #333; background: #111; color: #fff; border-radius: 5px; font-size: 16px; }
            button { background: #ff8c00; border: none; padding: 15px; width: 90%; font-weight: bold; border-radius: 5px; }
            #pwd-form { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); padding-top: 50px; }
        </style>
    </head>
    <body>
        <h1>VECTOR OS</h1>
        <p>ВЫБЕРИТЕ ВАШ WI-FI:</p>
        {% for net in networks %}
            <div class="net-item" onclick="selectNet('{{ net.ssid }}')">
                <span>{{ net.ssid }}</span>
                <span style="color: #555;">{{ net.signal }}%</span>
            </div>
        {% endfor %}
        <button onclick="location.reload()" style="background: #222; color: #fff; margin-top: 20px;">ОБНОВИТЬ СПИСОК</button>

        <div id="pwd-form">
            <h2 id="selected-ssid"></h2>
            <form method="POST">
                <input type="hidden" name="ssid" id="ssid-input">
                <input type="password" name="password" placeholder="Пароль" required autofocus>
                <button type="submit">ПОДКЛЮЧИТЬ</button>
                <button type="button" onclick="document.getElementById('pwd-form').style.display='none'" style="background:none; color:gray; margin-top:10px;">ОТМЕНА</button>
            </form>
        </div>

        <script>
            function selectNet(ssid) {
                document.getElementById('ssid-input').value = ssid;
                document.getElementById('selected-ssid').innerText = ssid;
                document.getElementById('pwd-form').style.display = 'block';
            }
        </script>
    </body>
    </html>
    '''
    return render_template_string(html, networks=networks)

# Добавь этот роут в свой файл setup_portal.py
@app.route('/status')
def status():
    # Если файл-флаг существует, значит интернет настроен
    flag_exists = os.path.exists("/home/yerniyaz/Desktop/vector/.first_run_completed")
    return {"connected": flag_exists}

if __name__ == '__main__':
    # Убедись, что порт 8081
    app.run(host='0.0.0.0', port=8081)