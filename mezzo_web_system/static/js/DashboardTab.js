// js/DashboardTab.js
import { ref, onMounted, computed } from 'vue';
import { store, BASE } from './store.js';

export default {
    template: `
        <div class="w-full h-full flex flex-col bg-[#0f1115]">
            <div class="flex-1 p-8 overflow-y-auto">
                <h2 class="text-2xl font-bold mb-6 text-gray-100 border-b border-gray-800 pb-2 flex justify-between items-center">
                    📊 戰術系統儀表板
                    <div class="flex gap-2">
                        <button @click="refreshAll"
                                class="bg-purple-600 hover:bg-purple-500 text-white px-4 py-1.5 rounded text-sm transition-colors flex items-center gap-2">
                            🔄 重新整理
                        </button>
                        <span v-if="store.alerts.length > 0" class="text-sm bg-red-600 text-white px-4 py-1 rounded-full animate-pulse shadow-[0_0_15px_rgba(220,38,38,0.6)]">
                            ⚠️ 發現入侵與異常事件
                        </span>
                    </div>
                </h2>

                <!-- NVR 伺服器資訊 -->
                <div class="mb-8">
                    <h3 class="text-lg font-bold text-[#00ffff] mb-4 flex items-center gap-2">
                        <span class="w-2 h-2 bg-[#00ffff] rounded-full"></span>
                        NVR 伺服器狀態
                    </h3>
                    <div v-if="nvrServerInfo" class="bg-gray-800 rounded-xl border border-gray-700 p-5 shadow-lg">
                        <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                            <div>
                                <span class="text-gray-400 text-xs uppercase">型號</span>
                                <p class="text-white font-bold">{{ nvrServerInfo.ModelName || '--' }}</p>
                            </div>
                            <div>
                                <span class="text-gray-400 text-xs uppercase">版本</span>
                                <p class="text-white font-mono">{{ nvrServerInfo.Version || '--' }}</p>
                            </div>
                            <div>
                                <span class="text-gray-400 text-xs uppercase">主機名</span>
                                <p class="text-white">{{ nvrServerInfo.HostName || '--' }}</p>
                            </div>
                            <div>
                                <span class="text-gray-400 text-xs uppercase">HTTP 連接埠</span>
                                <p class="text-white font-mono">{{ nvrServerInfo.PortBase || '--' }}</p>
                            </div>
                            <div>
                                <span class="text-gray-400 text-xs uppercase">RTSP 連接埠</span>
                                <p class="text-white font-mono">{{ nvrServerInfo.RTSPPort || '--' }}</p>
                            </div>
                            <div>
                                <span class="text-gray-400 text-xs uppercase">頻道數</span>
                                <p class="text-white font-bold">{{ nvrServerInfo.VideoCount }}/{{ nvrServerInfo.MaxVideoCount }}</p>
                            </div>
                        </div>
                    </div>
                    <div v-else class="bg-gray-800 rounded-xl border border-gray-700 p-5 shadow-lg text-center text-gray-400">
                        {{ loadingNvrInfo ? '載入中...' : '無法連線至 NVR' }}
                    </div>
                </div>

                <!-- NVR 攝影機列表 -->
                <div class="mb-8">
                    <h3 class="text-lg font-bold text-[#00ffff] mb-4 flex items-center gap-2">
                        <span class="w-2 h-2 bg-[#00ffff] rounded-full"></span>
                        NVR 攝影機狀態
                    </h3>
                    <div v-if="cameraList.length > 0" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                        <div v-for="(cam, idx) in cameraList" :key="idx"
                             class="bg-gray-800 rounded-xl border p-4 shadow-lg"
                             :class="cam.Enable === '1' ? 'border-green-500/30' : 'border-gray-700'">
                            <div class="flex items-start justify-between mb-3">
                                <div>
                                    <p class="text-lg font-bold text-white">頻道 {{ cam.channelID }}</p>
                                    <p class="text-xs text-gray-400">{{ cam.desc || '未命名' }}</p>
                                </div>
                                <span class="px-2 py-1 rounded text-xs font-bold border"
                                      :class="cam.Enable === '1'
                                              ? 'bg-green-900/30 text-green-400 border-green-800'
                                              : 'bg-gray-700 text-gray-400 border-gray-600'">
                                    {{ cam.Enable === '1' ? '✓ 啟用' : '✗ 停用' }}
                                </span>
                            </div>
                            <p v-if="cam.Enable === '1'" class="text-[10px] text-gray-500">錄影中...</p>
                        </div>
                    </div>
                    <div v-else class="bg-gray-800 rounded-xl border border-gray-700 p-5 shadow-lg text-center text-gray-400">
                        {{ loadingCameras ? '載入中...' : '無可用的攝影機' }}
                    </div>
                </div>

                <!-- 即時設備連線與事件狀態 -->
                <div class="mb-8">
                    <h3 class="text-lg font-bold text-[#00ffff] mb-4 flex items-center gap-2">
                        <span class="w-2 h-2 bg-[#00ffff] rounded-full animate-ping"></span>
                        即時設備連線與事件狀態 ({{ deviceCount }}/{{ store.devices.length }})
                    </h3>
                    <div v-if="store.devices.length > 0" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                        <div v-for="dev in store.devices" :key="dev.device_id"
                             class="bg-gray-800 rounded-xl border p-5 shadow-lg relative overflow-hidden transition-colors"
                             :class="store.alerts.includes(dev.device_id) ? 'border-red-500 shadow-[0_0_15px_rgba(220,38,38,0.2)]' : 'border-gray-700'">

                            <div class="absolute top-0 left-0 w-full h-1"
                                 :class="store.alerts.includes(dev.device_id) ? 'bg-red-500' : (store.telemetry[dev.device_id]?.battery < 20 ? 'bg-orange-500' : 'bg-[#00ffff]')"></div>

                            <div class="flex justify-between items-start mb-4">
                                <div>
                                    <h3 class="text-lg font-bold text-white">{{ dev.name }}</h3>
                                    <p class="text-xs text-gray-400 font-mono">{{ dev.device_id }}</p>
                                </div>
                                <div class="px-2 py-1 rounded text-xs font-bold border"
                                     :class="isDeviceOnline(dev.device_id)
                                             ? 'bg-green-900/30 text-green-400 border-green-800'
                                             : 'bg-red-900/30 text-red-400 border-red-800'">
                                    {{ isDeviceOnline(dev.device_id) ? '🟢 在線' : '🔴 離線' }}
                                </div>
                            </div>

                            <div class="space-y-3 text-sm">
                                <div class="flex justify-between border-b border-gray-700 pb-2">
                                    <span class="text-gray-400">設備電量</span>
                                    <span class="font-mono flex items-center gap-2 text-white">
                                        <div class="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
                                            <div class="h-full" :class="store.telemetry[dev.device_id]?.battery < 20 ? 'bg-orange-500' : 'bg-[#00ffff]'"
                                                 :style="\`width: \${store.telemetry[dev.device_id]?.battery || 0}%\`"></div>
                                        </div>
                                        <span :class="store.telemetry[dev.device_id]?.battery < 20 ? 'text-orange-400' : 'text-[#00ffff]'">{{ store.telemetry[dev.device_id]?.battery || 0 }}%</span>
                                    </span>
                                </div>

                                <div class="flex justify-between border-b border-gray-700 pb-2">
                                    <span class="text-gray-400">即時座標 (GPS)</span>
                                    <span class="font-mono" :class="store.alerts.includes(dev.device_id) ? 'text-red-400 font-bold' : 'text-gray-300'">
                                        {{ store.telemetry[dev.device_id]?.lat?.toFixed(5) || '---' }},
                                        {{ store.telemetry[dev.device_id]?.lng?.toFixed(5) || '---' }}
                                    </span>
                                </div>

                                <div class="flex justify-between border-b border-gray-700 pb-2">
                                    <span class="text-gray-400">SOS 警報狀態</span>
                                    <span class="font-mono font-bold" :class="store.telemetry[dev.device_id]?.sos ? 'text-red-500 animate-pulse' : 'text-gray-500'">
                                        {{ store.telemetry[dev.device_id]?.sos ? '🚨 警報觸發' : '安全' }}
                                    </span>
                                </div>
                                <div class="flex justify-between border-b border-gray-700 pb-2">
                                    <span class="text-gray-400">Mark 案件標記</span>
                                    <span class="font-mono text-gray-300">
                                        {{ store.telemetry[dev.device_id]?.mark || '無標記' }}
                                    </span>
                                </div>
                                <div class="flex justify-between pb-1">
                                    <span class="text-gray-400">配對心率帶 (HR)</span>
                                    <span class="font-mono flex items-center gap-1" :class="(store.telemetry[dev.device_id]?.hr || 0) > 130 ? 'text-red-400' : 'text-[#00ffff]'">
                                        <span v-if="store.telemetry[dev.device_id]?.hr" class="animate-pulse">❤️</span>
                                        {{ store.telemetry[dev.device_id]?.hr ? store.telemetry[dev.device_id].hr + ' bpm' : '未配對' }}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div v-else class="bg-gray-800 rounded-xl border border-gray-700 p-8 shadow-lg text-center text-gray-400">
                        無設備
                    </div>
                </div>

                <!-- 歷史事件與影像調閱 -->
                <div class="bg-gray-800 rounded-xl border border-gray-700 shadow-xl overflow-hidden">
                    <div class="bg-gray-900 p-4 border-b border-gray-700 flex items-center gap-2">
                        <span class="text-lg">🔍</span>
                        <h3 class="text-lg font-bold text-[#00ffff]">歷史事件與影像調閱</h3>
                    </div>

                    <div class="p-5 border-b border-gray-700 bg-gray-800/50 flex flex-wrap gap-4 items-end">
                        <div>
                            <label class="block text-xs text-gray-400 mb-1">起始時間</label>
                            <input type="datetime-local" v-model="searchQuery.startTime"
                                   class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white outline-none focus:border-[#00ffff]">
                        </div>
                        <div>
                            <label class="block text-xs text-gray-400 mb-1">結束時間</label>
                            <input type="datetime-local" v-model="searchQuery.endTime"
                                   class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white outline-none focus:border-[#00ffff]">
                        </div>
                        <div>
                            <label class="block text-xs text-gray-400 mb-1">頻道</label>
                            <select v-model="searchQuery.channel"
                                    class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white outline-none focus:border-[#00ffff]">
                                <option v-for="n in 12" :key="n-1" :value="n-1">頻道 {{ n-1 }}</option>
                            </select>
                        </div>
                        <button @click="executeSearch" :disabled="searchLoading || !searchQuery.startTime || !searchQuery.endTime"
                                class="bg-[#00ffff] hover:bg-[#00cccc] disabled:bg-gray-600 disabled:text-gray-400 text-gray-900 px-6 py-2 rounded font-bold transition-colors shadow-[0_0_10px_rgba(0,255,255,0.4)] h-[42px]">
                            {{ searchLoading ? '查詢中...' : '搜尋' }}
                        </button>
                    </div>

                    <div v-if="searchError" class="px-5 py-3 bg-red-900/30 border-b border-red-800 text-red-400 text-sm">
                        {{ searchError }}
                    </div>

                    <div class="p-0 overflow-x-auto">
                        <table class="w-full text-left text-sm text-gray-300 whitespace-nowrap">
                            <thead class="bg-gray-900 text-gray-400 border-b border-gray-700">
                                <tr>
                                    <th class="p-4 font-medium">觸發時間</th>
                                    <th class="p-4 font-medium">事件類型</th>
                                    <th class="p-4 font-medium">事件描述</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-if="searchLoading" class="border-b border-gray-800">
                                    <td colspan="3" class="p-8 text-center text-gray-500 animate-pulse">查詢 NVR 中...</td>
                                </tr>
                                <tr v-else-if="searchResults.length === 0" class="border-b border-gray-800">
                                    <td colspan="3" class="p-8 text-center text-gray-500">請輸入時間範圍後點擊搜尋</td>
                                </tr>
                                <tr v-for="(event, idx) in searchResults" :key="idx"
                                    class="border-b border-gray-700 hover:bg-gray-700/50 transition-colors">
                                    <td class="p-4 font-mono text-gray-300">{{ event.time }}</td>
                                    <td class="p-4">
                                        <span class="px-2 py-1 rounded text-xs font-bold bg-gray-700 text-gray-300 border border-gray-600">
                                            {{ event.type }}
                                        </span>
                                    </td>
                                    <td class="p-4 text-gray-400">{{ event.details }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    `,
    setup() {
        const nvrServerInfo = ref(null);
        const cameraList = ref([]);
        const loadingNvrInfo = ref(false);
        const loadingCameras = ref(false);
        const devicePositions = ref({});

        const searchQuery = ref({
            startTime: '',
            endTime:   '',
            channel:   0
        });

        const searchResults = ref([]);
        const searchLoading = ref(false);
        const searchError   = ref('');

        const deviceCount = computed(() => {
            return Object.keys(devicePositions.value).length;
        });

        const isDeviceOnline = (deviceId) => {
            const pos = devicePositions.value[deviceId];
            if (!pos) return false;
            const lastUpdate = new Date(pos.last_update);
            const now = new Date();
            // 超過 5 分鐘未更新視為離線
            return (now - lastUpdate) < 5 * 60 * 1000;
        };

        const fetchNvrInfo = async () => {
            loadingNvrInfo.value = true;
            try {
                const res = await fetch(`${BASE}/api/nvr/server_info`);
                if (res.ok) {
                    nvrServerInfo.value = await res.json();
                }
            } catch (e) {
                console.error('NVR info error:', e);
            } finally {
                loadingNvrInfo.value = false;
            }
        };

        const fetchCameras = async () => {
            loadingCameras.value = true;
            try {
                const res = await fetch(`${BASE}/api/nvr/cameras`);
                if (res.ok) {
                    const data = await res.json();
                    cameraList.value = Array.isArray(data) ? data : data.cameras || [];
                }
            } catch (e) {
                console.error('Cameras fetch error:', e);
            } finally {
                loadingCameras.value = false;
            }
        };

        const fetchDevicePositions = async () => {
            try {
                const res = await fetch(`${BASE}/api/devices/positions`);
                if (res.ok) {
                    devicePositions.value = await res.json();
                }
            } catch (e) {
                console.error('Device positions error:', e);
            }
        };

        const refreshAll = () => {
            fetchNvrInfo();
            fetchCameras();
            fetchDevicePositions();
        };

        const executeSearch = async () => {
            if (!searchQuery.value.startTime || !searchQuery.value.endTime) return;
            searchLoading.value = true;
            searchError.value   = '';
            searchResults.value = [];

            try {
                const toNvrTime = (dt) => dt.replace('T', ' ') + ':00';
                const params = new URLSearchParams({
                    begin_time: toNvrTime(searchQuery.value.startTime),
                    end_time:   toNvrTime(searchQuery.value.endTime),
                    channel:    searchQuery.value.channel,
                    start: 0,
                    limit: 100
                });

                const res = await fetch(`${BASE}/api/nvr/query_event?${params}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();

                if (data.data && Array.isArray(data.data)) {
                    searchResults.value = data.data.map((evt, idx) => ({
                        id:      idx,
                        time:    evt.EventTime || evt.time || '未知時間',
                        type:    evt.EventType || evt.type || 'UNKNOWN',
                        details: evt.EventDesc || evt.description || '--'
                    }));
                }
                if (searchResults.value.length === 0) {
                    searchError.value = '該時段無事件紀錄';
                }
            } catch (e) {
                searchError.value = '查詢失敗：' + e.message;
            } finally {
                searchLoading.value = false;
            }
        };

        onMounted(() => {
            refreshAll();
            // 每 10 秒更新一次設備位置和 NVR 資訊
            const interval = setInterval(refreshAll, 10000);
            return () => clearInterval(interval);
        });

        return {
            store,
            nvrServerInfo,
            cameraList,
            loadingNvrInfo,
            loadingCameras,
            devicePositions,
            deviceCount,
            isDeviceOnline,
            searchQuery,
            searchResults,
            searchLoading,
            searchError,
            executeSearch,
            refreshAll
        };
    }
};