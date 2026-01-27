import { useState, useEffect } from "react";
import { Box, Progress, Text, MantineProvider } from "@mantine/core";
import { useMirrorData } from "./hooks/useMirrorData";

import { Dashboard } from "./pages/Dashboard";
import { Hub } from "./pages/Hub";
import { Settings } from "./pages/Settings";

// Electron IPC (если запущен в Electron)
const ipc = window.require ? window.require("electron").ipcRenderer : null;

export default function App() {
  const [page, setPage] = useState(0);
  
  // Достаем данные и функции Wi-Fi из нашего хука
  const { 
    time, 
    sensors, 
    weather, 
    news, 
    updStatus, 
    updProgress, 
    appVersion, 
    setUpdStatus,
    fetchData,
    wifiList,        // Список сетей
    getWifiList,     // Функция сканирования
    connectToWifi    // Функция подключения
  } = useMirrorData();

  // Системные команды Electron
  const launch = (data, type, isTV = false) => ipc?.send("launch", { data, type, isTV });
  const updateMirror = () => ipc?.send("check-for-updates");

  // Универсальная функция отправки команд на Python-бэкенд (5005)
  const sendCmd = async (endpoint) => {
    setUpdStatus(`ВЫПОЛНЕНИЕ: ${endpoint.toUpperCase()}...`);
    try {
      const res = await fetch(`http://127.0.0.1:5005/api/system/${endpoint}`, { 
        method: "POST" 
      });
      if (res.ok) {
        setUpdStatus("УСПЕШНО");
      } else {
        setUpdStatus("ОШИБКА СЕРВЕРА");
      }
    } catch (e) {
      setUpdStatus("СВЯЗЬ ПОТЕРЯНА");
    }
    setTimeout(() => setUpdStatus(""), 3000);
  };

  // Обновление Python-части (Git Pull + Датчики)
  const updatePython = async () => {
    setUpdStatus("ОБНОВЛЕНИЕ СИСТЕМЫ..."); // Статус на экране
    try {
      const res = await fetch("http://127.0.0.1:5005/api/system/update-python", { 
        method: "POST" 
      });

      if (res.ok) {
        setUpdStatus("КОД ЗАГРУЖЕН. ПЕРЕЗАПУСК...");
        
        // Вежливая пауза 4 секунды, чтобы bridge.py успел перезагрузиться
        setTimeout(async () => {
          try {
            await fetchData(); // Обновляем данные с новых датчиков
            setUpdStatus("СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА");
          } catch (err) {
            setUpdStatus("ДАТЧИКИ ЕЩЕ СПЯТ");
          }
          setTimeout(() => setUpdStatus(""), 2000);
        }, 4000);

      } else {
        setUpdStatus("ОШИБКА ОБНОВЛЕНИЯ");
        setTimeout(() => setUpdStatus(""), 3000);
      }
    } catch (e) {
      setUpdStatus("БРИДЖ НЕ ОТВЕЧАЕТ");
      setTimeout(() => setUpdStatus(""), 3000);
    }
  };

  // Навигация клавишами
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "ArrowRight") setPage((p) => Math.min(p + 1, 2));
      if (e.key === "ArrowLeft") setPage((p) => Math.max(p - 1, 0));
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <MantineProvider defaultColorScheme="dark">
      <Box style={{ 
        backgroundColor: "#000", 
        height: "100vh", 
        width: "100vw", 
        overflow: "hidden", 
        color: "white",
        // ГЛАВНАЯ ФИШКА: Скрываем курсор только на 0 странице (Dashboard)
        cursor: page === 0 ? "none" : "default" 
      }}>

        {/* СТРОГИЙ ИНДИКАТОР СТАТУСА */}
        {updStatus && (
          <Box style={{ 
            position: "fixed", 
            top: 40, 
            left: "50%", 
            transform: "translateX(-50%)", 
            zIndex: 10000, 
            width: 320, 
            background: "rgba(5,5,5,0.95)", 
            padding: "20px", 
            border: "1px solid #111", 
            borderRadius: "4px" 
          }}>
            <Text size="xs" fw={900} mb={updProgress > 0 ? 10 : 0} ta="center" style={{ letterSpacing: "3px" }}>
              {updStatus.toUpperCase()}
            </Text>
            {updProgress > 0 && <Progress value={updProgress} color="white" size="xs" animated />}
          </Box>
        )}

        {/* КОНТЕЙНЕР СЛАЙДОВ (Dashboard -> Hub -> Settings) */}
        <Box style={{ 
          display: "flex", 
          width: "300vw", 
          height: "100vh", 
          transition: "transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)", 
          transform: `translateX(-${page * 100}vw)` 
        }}>
          {/* Слайд 0: Главный экран (без мышки) */}
          <Dashboard time={time} weather={weather} sensors={sensors} news={news} />
          
          {/* Слайд 1: Меню приложений (с мышкой) */}
          <Hub launch={launch} />
          
          {/* Слайд 2: Настройки (с мышкой) */}
          <Settings 
            sendCmd={sendCmd} 
            updateMirror={updateMirror} 
            updatePython={updatePython} 
            appVersion={appVersion}
            wifiList={wifiList}
            getWifiList={getWifiList}
            connectToWifi={connectToWifi}
          />
        </Box>

        {/* МИНИМАЛИСТИЧНЫЕ ТОЧКИ ПАГИНАЦИИ */}
        <Box style={{ position: "fixed", bottom: 40, left: "50%", transform: "translateX(-50%)", zIndex: 100 }}>
          <div style={{ display: "flex", gap: "15px" }}>
            {[0, 1, 2].map((i) => (
              <Box key={i} style={{ 
                width: i === page ? 25 : 8, 
                height: 8, 
                borderRadius: 4, 
                backgroundColor: i === page ? "white" : "#111", 
                border: i === page ? "none" : "1px solid #222",
                transition: "all 0.4s ease" 
              }} />
            ))}
          </div>
        </Box>

      </Box>
    </MantineProvider>
  );
}