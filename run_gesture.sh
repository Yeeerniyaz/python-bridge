#!/bin/bash
# Путь к твоему проекту
PATH_PROJECT="/home/yerniyaz/Desktop/vector/python"
cd $PATH_PROJECT

# Активация твоего виртуального окружения
source .venv/bin/activate

# Настройки дисплея для работы с мышью
export DISPLAY=:0
export XAUTHORITY=/home/yerniyaz/.Xauthority

# Запуск
python3 gesture_control.py