import { useEffect, useRef, useState, useCallback } from 'react'

const WS_BASE_URL = import.meta.env.VITE_API_URL?.replace(/^http/, 'ws') || 'ws://localhost:8000'

export function useWebSocket(token) {
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState(null)
  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const pingIntervalRef = useRef(null)

  const connect = useCallback(() => {
    if (!token) return

    // Очищаем предыдущие таймеры
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
    }

    const wsUrl = `${WS_BASE_URL}/ws?token=${token}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      // Отправляем ping каждые 25 секунд, чтобы держать соединение
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('')
        }
      }, 25000)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setLastMessage(data)
      } catch (e) {
        // Игнорируем не-JSON сообщения (ping-ответы)
      }
    }

    ws.onclose = () => {
      setConnected(false)
      // Переподключаемся через 5 секунд
      reconnectTimeoutRef.current = setTimeout(connect, 5000)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [token])

  useEffect(() => {
    connect()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
    }
  }, [connect])

  return { connected, lastMessage }
}