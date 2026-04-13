// js/store.js
import { reactive } from 'vue';

// 若部署在子路徑 /mezzo/ 下，由 index_3D.html 設定 window.MEZZO_BASE
export const BASE = (typeof window !== 'undefined' && window.MEZZO_BASE) ? window.MEZZO_BASE : '';

export const store = reactive({
    currentUser: null,
    devices: [],
    telemetry: {},
    geofences: [],
    alerts: [],
    sosAlerts: [],   // SOS 緊急告警佇列，由 WebSocket sos_alert 事件推入

    async fetchDevices() {
        if (!this.currentUser) return;
        try {
            const res = await fetch(`${BASE}/api/devices?username=${this.currentUser.username}`);
            this.devices = await res.json();
        } catch (e) {
            console.error("無法取得設備列表", e);
        }
    },

    async fetchGeofences() {
        try {
            const res = await fetch(`${BASE}/api/geofences`);
            this.geofences = await res.json();
        } catch (e) {
            console.error("無法取得警戒區列表", e);
        }
    },

    connectWebSocket() {
        const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${wsProto}//${location.host}${BASE}/ws/map-data`);
        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'telemetry_update') {
                this.telemetry = msg.data;
                this.checkGeofence();
            } else if (msg.type === 'sos_alert') {
                this.sosAlerts.push(msg.data);
            }
        };
    },

    checkGeofence() {
        this.alerts = []; // 每次檢查前清空警報
        for (const [deviceId, state] of Object.entries(this.telemetry)) {
            if (state.status === '離線') continue;
            
            let isInsideAny = false;
            // 比對所有啟用的警戒區
            for (const fence of this.geofences) {
                if (!fence.is_enabled) continue;
                try {
                    const points = JSON.parse(fence.points); // 解析 [{lng, lat}]
                    const polygon = points.map(p => [p.lng, p.lat]);
                    if (this.isPointInPolygon([state.lng, state.lat], polygon)) {
                        isInsideAny = true;
                        break;
                    }
                } catch(e) {}
            }

            if (isInsideAny) {
                this.alerts.push(deviceId);
            }
        }
    },

    // 核心演算法：判斷點是否在多邊形內 (Ray-Casting)
    isPointInPolygon(point, vs) {
        let x = point[0], y = point[1];
        let inside = false;
        for (let i = 0, j = vs.length - 1; i < vs.length; j = i++) {
            let xi = vs[i][0], yi = vs[i][1];
            let xj = vs[j][0], yj = vs[j][1];
            let intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }
});