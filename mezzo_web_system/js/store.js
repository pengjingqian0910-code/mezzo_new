// js/store.js
import { reactive } from 'vue';

export const store = reactive({
    currentUser: null,
    devices: [],
    telemetry: {},
    geofences: [],
    alerts: [], 

    async fetchDevices() {
        if (!this.currentUser) return;
        try {
            const res = await fetch(`/api/devices?username=${this.currentUser.username}`);
            this.devices = await res.json();
        } catch (e) {
            console.error("無法取得設備列表", e);
        }
    },

    async fetchGeofences() {
        try {
            const res = await fetch('/api/geofences');
            this.geofences = await res.json();
        } catch (e) {
            console.error("無法取得警戒區列表", e);
        }
    },

    connectWebSocket() {
        const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${wsProto}//${location.host}/ws/map-data`);
        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'telemetry_update') {
                this.telemetry = msg.data;
                this.checkGeofence();
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