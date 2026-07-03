// js/SosModal.js — Global SOS Emergency Alert Modal
// Triggered by store.sosAlerts (pushed by WebSocket sos_alert messages)
// Shows: GPS mini-map, live MJPEG video, remote audio monitoring

import { ref, computed, watch, onUnmounted, nextTick } from 'vue';
import { store, BASE } from './store.js';

// ── AAC audio playback via Web Audio API decodeAudioData ─────────────────────
const PAYLOAD_TAG_LEN  = 32;
const PAYLOAD_UUID_LEN = 128;
const PAYLOAD_HDR_LEN  = PAYLOAD_TAG_LEN + PAYLOAD_UUID_LEN;

function readTag(buf) {
    return new TextDecoder('ascii').decode(buf.slice(0, PAYLOAD_TAG_LEN)).replace(/\x00/g, '').trim();
}

function makeAacQueue(audioCtx) {
    return { chunks: [], nextPlayTime: 0, ctx: audioCtx, timer: null };
}

function pushAacChunk(q, bytes) {
    if (!bytes || bytes.byteLength < 4) return;
    q.chunks.push(bytes);
    if (!q.timer) {
        q.timer = setTimeout(() => _flushAac(q), 80);
    }
}

function _flushAac(q) {
    q.timer = null;
    if (q.chunks.length === 0) return;
    const all = q.chunks.splice(0);
    const total = all.reduce((s, c) => s + c.byteLength, 0);
    const merged = new Uint8Array(total);
    let pos = 0;
    for (const c of all) { merged.set(c, pos); pos += c.byteLength; }
    q.ctx.decodeAudioData(merged.buffer, (decoded) => {
        const src = q.ctx.createBufferSource();
        src.buffer = decoded;
        src.connect(q.ctx.destination);
        const startAt = Math.max(q.nextPlayTime, q.ctx.currentTime + 0.05);
        src.start(startAt);
        q.nextPlayTime = startAt + decoded.duration;
        if (q.chunks.length > 0) {
            q.timer = setTimeout(() => _flushAac(q), 80);
        }
    }, (err) => {
        console.warn('[SosModal] AAC decode error:', err);
        if (q.chunks.length > 0) {
            q.timer = setTimeout(() => _flushAac(q), 80);
        }
    });
}

// ── Component ─────────────────────────────────────────────────────────────────
export default {
    template: `
    <div v-if="store.sosAlerts.length > 0"
         class="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center"
         style="z-index: 99999;">

        <!-- Flashing red border glow -->
        <div class="bg-gray-900 border-2 border-red-500 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
             style="width: min(960px, 95vw); max-height: 92vh; box-shadow: 0 0 80px rgba(239,68,68,0.55);">

            <!-- ── Header ─────────────────────────────────────────────── -->
            <div class="bg-gradient-to-r from-red-950 to-red-900 px-5 py-3.5 flex items-center justify-between border-b border-red-700 shrink-0">
                <div class="flex items-center gap-3">
                    <span class="text-3xl" style="animation: pulse 1s infinite;">🆘</span>
                    <div>
                        <h2 class="text-lg font-black text-red-200 tracking-widest uppercase">SOS Emergency Alert</h2>
                        <p class="text-[11px] text-red-400 font-mono mt-0.5">
                            {{ currentAlert?.device_id }}
                            &nbsp;·&nbsp; {{ currentAlert?.channel }}
                            &nbsp;·&nbsp; {{ currentAlert?.timestamp }}
                        </p>
                    </div>
                </div>

                <div class="flex items-center gap-2 shrink-0">
                    <div v-if="store.sosAlerts.length > 1" class="flex items-center gap-1.5">
                        <button @click="prev"
                                :disabled="currentIdx === 0"
                                class="w-6 h-6 bg-red-800 hover:bg-red-700 disabled:opacity-30 text-white rounded text-xs font-bold flex items-center justify-center">◀</button>
                        <span class="text-xs text-red-300 font-bold px-1">{{ currentIdx+1 }}&nbsp;/&nbsp;{{ store.sosAlerts.length }}</span>
                        <button @click="next"
                                :disabled="currentIdx === store.sosAlerts.length-1"
                                class="w-6 h-6 bg-red-800 hover:bg-red-700 disabled:opacity-30 text-white rounded text-xs font-bold flex items-center justify-center">▶</button>
                    </div>

                    <button @click="dismiss"
                            class="bg-gray-700 hover:bg-gray-600 text-white px-4 py-1.5 rounded-lg text-sm font-bold transition-colors">
                        Dismiss
                    </button>
                    <button v-if="store.sosAlerts.length > 1"
                            @click="dismissAll"
                            class="bg-red-800 hover:bg-red-700 text-white px-4 py-1.5 rounded-lg text-sm font-bold transition-colors">
                        Dismiss All ({{ store.sosAlerts.length }})
                    </button>
                </div>
            </div>

            <!-- ── Body ───────────────────────────────────────────────── -->
            <div class="flex flex-1 min-h-0">

                <!-- Left: Leaflet mini-map -->
                <div class="flex-1 relative min-h-0" style="min-height: 420px;">
                    <div id="sosMapContainer" class="w-full h-full"></div>
                    <div class="absolute bottom-3 left-3 bg-black/75 text-white text-[11px] font-mono px-3 py-1.5 rounded-lg"
                         style="z-index: 1000;">
                        📍 {{ currentAlert?.lat?.toFixed(6) }},&nbsp;{{ currentAlert?.lng?.toFixed(6) }}
                    </div>
                </div>

                <!-- Right panel: video + audio + info -->
                <div class="w-76 flex flex-col border-l border-gray-800 bg-gray-950 shrink-0" style="width:300px;">

                    <!-- Live video -->
                    <div class="border-b border-gray-800">
                        <div class="bg-gray-800/80 px-3 py-2 flex items-center gap-2">
                            <span class="w-2 h-2 bg-red-500 rounded-full" style="animation: pulse 1s infinite;"></span>
                            <span class="text-xs font-bold text-gray-300">Live Camera</span>
                            <span class="ml-auto text-[9px] text-gray-500 font-mono truncate max-w-[120px]">{{ currentAlert?.device_id }}</span>
                        </div>
                        <div class="bg-black flex items-center justify-center overflow-hidden" style="aspect-ratio:16/9;">
                            <img v-if="deviceMjpegUrl"
                                 :src="deviceMjpegUrl"
                                 :key="deviceMjpegUrl"
                                 style="width:100%;height:100%;object-fit:contain;display:block;">
                            <div v-else class="text-[11px] text-gray-600 text-center p-4">
                                📷 No camera matched<br>
                                <span class="font-mono text-[9px]">{{ currentAlert?.device_id }}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Audio Monitor -->
                    <div class="p-3 border-b border-gray-800">
                        <div class="bg-gray-900 rounded-xl p-3 border transition-colors"
                             :class="isMonitoring ? 'border-green-600/60' : 'border-gray-700'">
                            <div class="flex items-center gap-2 mb-2">
                                <span class="text-sm">🎧</span>
                                <span class="text-xs font-bold text-gray-300">Remote Audio Monitor</span>
                                <span v-if="isMonitoring"
                                      class="ml-auto text-[9px] text-green-400 bg-green-900/40 px-2 py-0.5 rounded"
                                      style="animation: pulse 1s infinite;">● LIVE</span>
                            </div>
                            <button @click="isMonitoring ? stopMonitor() : startMonitor()"
                                    :class="isMonitoring
                                        ? 'bg-red-700 hover:bg-red-600 text-white'
                                        : 'bg-green-800 hover:bg-green-700 text-white'"
                                    class="w-full py-1.5 rounded font-bold text-xs transition-colors">
                                {{ isMonitoring ? '⏹ Stop Monitoring' : '🎧 Start Monitoring' }}
                            </button>
                            <p class="text-[9px] text-gray-600 mt-1.5 text-center">
                                Channel: {{ currentAlert?.channel }}
                            </p>
                        </div>
                    </div>

                    <!-- Alert details -->
                    <div class="p-3 flex-1">
                        <div class="bg-gray-900 rounded-xl p-3 border border-gray-800 text-[10px] space-y-2">
                            <div class="text-[9px] text-red-500 font-bold uppercase tracking-wider mb-1">Alert Details</div>
                            <div class="flex justify-between gap-2">
                                <span class="text-gray-500 shrink-0">Device</span>
                                <span class="text-red-300 font-mono font-bold text-right truncate">{{ currentAlert?.device_id }}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-500">Channel</span>
                                <span class="text-gray-200 font-mono">{{ currentAlert?.channel }}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-500">Time</span>
                                <span class="text-gray-300 font-mono">{{ currentAlert?.timestamp }}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-500">Lat</span>
                                <span class="text-gray-300 font-mono">{{ currentAlert?.lat?.toFixed(6) }}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-gray-500">Lng</span>
                                <span class="text-gray-300 font-mono">{{ currentAlert?.lng?.toFixed(6) }}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `,

    setup() {
        let sosMap    = null;
        let sosMarker = null;
        let audioCtx  = null;
        let aacQueue  = null;
        let monitorWs = null;

        const currentIdx   = ref(0);
        const isMonitoring = ref(false);
        const nvrDevices   = ref([]);
        let nvrIp   = '118.163.141.80';
        let nvrPort = 80;
        let nvrAuth = '';

        const currentAlert = computed(() => store.sosAlerts[currentIdx.value] || null);

        const deviceMjpegUrl = computed(() => {
            if (!currentAlert.value) return null;
            const dev = nvrDevices.value.find(d => d.device_id === currentAlert.value.device_id);
            return dev?.mjpeg_url || null;
        });

        const fetchNvrDevices = async () => {
            try {
                const cfgRes = await fetch(`${BASE}/api/nvr/config`);
                const cfg    = cfgRes.ok ? await cfgRes.json() : null;
                const res    = await fetch(`${BASE}/api/nvr/cameras`);
                const data   = res.ok ? await res.json() : [];
                nvrIp   = cfg?.ip        || '118.163.141.80';
                nvrPort = cfg?.http_port || 80;
                nvrAuth = cfg?.auth_b64  || '';
                nvrDevices.value = (data || []).map(c => ({
                    device_id: c.desc || `CH${c.channelID}`,
                    channelID: c.channelID,
                    mjpeg_url: `http://${nvrIp}:${nvrPort}/mjpeg_stream.cgi?Auth=${nvrAuth}&ch=${c.channelID}`
                }));
            } catch (e) {
                console.error('[SosModal] NVR fetch failed:', e);
            }
        };

        const initOrUpdateMap = async () => {
            await nextTick();
            const alert = currentAlert.value;
            if (!alert) return;

            const lat = Number(alert.lat);
            const lng = Number(alert.lng);
            if (!lat && !lng) return;

            const el = document.getElementById('sosMapContainer');
            if (!el) return;

            if (!sosMap) {
                sosMap = L.map('sosMapContainer', { zoomControl: true }).setView([lat, lng], 16);
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '© OpenStreetMap', maxZoom: 19
                }).addTo(sosMap);
            } else {
                sosMap.invalidateSize();
                sosMap.setView([lat, lng], 16);
            }

            if (sosMarker) { sosMap.removeLayer(sosMarker); sosMarker = null; }

            const sosIcon = L.divIcon({
                className: '',
                html: `<div style="
                    width:28px;height:28px;border-radius:50%;
                    background:rgba(239,68,68,0.9);
                    border:3px solid #fff;
                    box-shadow:0 0 0 4px rgba(239,68,68,0.4);
                    display:flex;align-items:center;justify-content:center;
                    font-size:14px;font-weight:900;color:#fff;
                ">🆘</div>`,
                iconSize:   [28, 28],
                iconAnchor: [14, 14]
            });

            sosMarker = L.marker([lat, lng], { icon: sosIcon })
                .addTo(sosMap)
                .bindPopup(
                    `<b style="color:#dc2626;">🆘 SOS</b><br>
                    ${alert.device_id}<br>
                    <span style="font-size:11px;color:#6b7280;">${alert.timestamp}</span>`,
                    { maxWidth: 220 }
                )
                .openPopup();
        };

        const startMonitor = () => {
            if (isMonitoring.value || !currentAlert.value) return;
            const targetChannel = currentAlert.value.channel;

            try { audioCtx = new AudioContext(); } catch (e) { return; }

            const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            monitorWs = new WebSocket(`${wsProto}//${location.host}${BASE}/ws/ptt`);
            aacQueue = makeAacQueue(audioCtx);

            monitorWs.onopen = () => { isMonitoring.value = true; };

            monitorWs.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (!msg.topic || !msg.topic.includes(targetChannel)) return;
                    const binStr = atob(msg.payload);
                    const bytes  = new Uint8Array(binStr.length);
                    for (let i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i);
                    const tag = readTag(bytes);
                    if (tag === 'AUDIODATA') pushAacChunk(aacQueue, bytes.slice(PAYLOAD_HDR_LEN));
                } catch (e) { /* skip malformed */ }
            };

            monitorWs.onclose  = () => { isMonitoring.value = false; };
            monitorWs.onerror  = () => { isMonitoring.value = false; };
        };

        const stopMonitor = () => {
            if (monitorWs) { monitorWs.close(); monitorWs = null; }
            if (aacQueue)  { if (aacQueue.timer) { clearTimeout(aacQueue.timer); } aacQueue = null; }
            if (audioCtx)  { audioCtx.close().catch(() => {}); audioCtx = null; }
            isMonitoring.value = false;
        };

        const prev = () => { if (currentIdx.value > 0) currentIdx.value--; };
        const next = () => { if (currentIdx.value < store.sosAlerts.length - 1) currentIdx.value++; };

        const dismiss = () => {
            stopMonitor();
            store.sosAlerts.splice(currentIdx.value, 1);
            if (currentIdx.value >= store.sosAlerts.length && currentIdx.value > 0) currentIdx.value--;
            if (store.sosAlerts.length === 0 && sosMap) { sosMap.remove(); sosMap = null; sosMarker = null; }
        };

        const dismissAll = () => {
            stopMonitor();
            store.sosAlerts.splice(0);
            currentIdx.value = 0;
            if (sosMap) { sosMap.remove(); sosMap = null; sosMarker = null; }
        };

        watch(currentAlert, (newVal) => { if (newVal) initOrUpdateMap(); });
        watch(() => store.sosAlerts.length, (len, prevLen) => { if (len > 0 && prevLen === 0) initOrUpdateMap(); });

        onUnmounted(() => {
            stopMonitor();
            if (sosMap) { sosMap.remove(); sosMap = null; }
        });

        fetchNvrDevices();

        return {
            store, currentIdx, currentAlert, isMonitoring, deviceMjpegUrl,
            prev, next, dismiss, dismissAll, startMonitor, stopMonitor
        };
    }
};
