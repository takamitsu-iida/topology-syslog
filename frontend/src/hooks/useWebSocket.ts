import { useEffect, useRef } from 'react'
import type { Incident } from '../types'

interface WsEvent {
  type: 'incident.new'
  incident: Incident
}

/**
 * /ws/incidents へ接続し、新規インシデント発生時にコールバックを呼ぶ。
 * コンポーネントのアンマウント時に自動切断する。
 */
export function useIncidentWebSocket(onNewIncident: (inc: Incident) => void): void {
  const wsBase =
    (import.meta.env.VITE_WS_URL as string | undefined) ??
    `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/incidents`

  // コールバックの参照をメモ化してエフェクトの再実行を防ぐ
  const cbRef = useRef(onNewIncident)
  cbRef.current = onNewIncident

  useEffect(() => {
    const ws = new WebSocket(wsBase)
    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as WsEvent
        if (data.type === 'incident.new') {
          cbRef.current(data.incident)
        }
      } catch {
        // 不正なメッセージは無視
      }
    }
    ws.onerror = () => ws.close()
    return () => ws.close()
  }, [wsBase])
}
