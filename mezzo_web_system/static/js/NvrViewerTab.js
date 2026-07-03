// js/NvrViewerTab.js
// NVR 即時監控與回放頁籤（使用 Mezzo Bearer Token，免另外登入 NVR）
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { store, BASE } from './store.js';

export default {
    template: `
    <div class="w-full h-full flex flex-col overflow-hidden bg-[#0f1115]">

        <!-- Header -->
        <div class="flex-shrink-0 px-6 py-3 border-b border-gray-800 flex items-center gap-4 bg-gray-900">
            <div>
                <h2 class="text-xl font-bold text-indigo-400 flex items-center gap-2">
                    <span>📹</span> NVR 影像監控
                </h2>
                <p class="text-xs text-gray-500 mt-0.5">{{ nvrInfo || '即時串流 · 歷史回放 · 下載' }}</p>
            </div>
            <div class="ml-auto flex items-center gap-3">
                <div class="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border"
                     :class="cameras.length > 0
                         ? 'bg-green-900/30 border-green-700 text-green-400'
                         : 'bg-gray-800 border-gray-700 text-gray-500'">
                    <span class="w-2 h-2 rounded-full"
                          :class="cameras.length > 0 ? 'bg-green-400 animate-pulse' : 'bg-gray-600'"></span>
                    {{ cameras.length > 0 ? cameras.length + ' 路攝影機' : '未連線' }}
                </div>
                <!-- Grid layout switcher -->
                <div class="flex gap-1">
                    <button v-for="n in [2,3,4]" :key="n"
                            @click="gridCols = n"
                            :class="gridCols===n ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'"
                            class="px-2 py-1 rounded text-xs transition-colors">{{ n }}×</button>
                </div>
                <button @click="loadCameras" class="text-gray-500 hover:text-indigo-400 text-lg transition-colors" title="重新整理">↻</button>
                <a :href="BASE+'/nvr'" target="_blank"
                   class="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded border border-gray-700 transition-colors">
                    開新視窗 ↗
                </a>
            </div>
        </div>

        <div class="flex flex-1 overflow-hidden">

            <!-- ── Camera Grid ── -->
            <div class="flex-1 overflow-y-auto p-4">
                <div v-if="cameras.length === 0" class="flex items-center justify-center h-full">
                    <div class="text-center">
                        <div class="w-8 h-8 border-2 border-gray-700 border-t-indigo-500 rounded-full animate-spin mx-auto mb-3"></div>
                        <div class="text-gray-500 text-sm">載入攝影機列表中…</div>
                        <div v-if="loadError" class="text-red-400 text-xs mt-2 max-w-xs">{{ loadError }}</div>
                    </div>
                </div>
                <div v-else
                     :style="'grid-template-columns: repeat(' + gridCols + ', minmax(0, 1fr))'"
                     class="grid gap-3">
                    <div v-for="cam in cameras" :key="cam.ch"
                         @click="selectCamera(cam)"
                         class="relative bg-black rounded-lg overflow-hidden cursor-pointer border-2 transition-colors"
                         :class="selectedCam && selectedCam.ch === cam.ch
                             ? 'border-indigo-500' : 'border-gray-800 hover:border-gray-600'"
                         style="aspect-ratio:16/9">

                        <!-- MJPEG live stream -->
                        <img v-if="!cam.error"
                             :src="mjpegUrl(cam.ch)"
                             class="w-full h-full object-contain"
                             :alt="cam.name"
                             @error="cam.error = true">

                        <!-- Snapshot fallback -->
                        <div v-else class="w-full h-full flex items-center justify-center bg-gray-950">
                            <img :src="snapshotUrl(cam.ch)"
                                 class="w-full h-full object-contain"
                                 @error="cam.snapError = true"
                                 v-if="!cam.snapError">
                            <div v-else class="text-gray-700 text-xs text-center">
                                <div class="text-4xl mb-2 opacity-40">📷</div>
                                <div>CH{{ cam.ch }} 無法連線</div>
                            </div>
                        </div>

                        <!-- Channel label -->
                        <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5 flex items-end justify-between">
                            <span class="text-xs font-bold text-white truncate">CH{{ cam.ch }}: {{ cam.name }}</span>
                            <div class="flex items-center gap-1">
                                <span v-if="selectedCam && selectedCam.ch === cam.ch"
                                      class="text-[10px] bg-indigo-600 text-white px-1.5 rounded font-bold">已選</span>
                                <span class="text-[10px] px-1.5 py-0.5 rounded"
                                      :class="cam.enabled ? 'bg-green-900/70 text-green-300' : 'bg-gray-900 text-gray-600'">
                                    {{ cam.enabled ? 'ON' : 'OFF' }}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- ── Playback Sidebar ── -->
            <div v-if="selectedCam" class="w-80 bg-gray-900 border-l border-gray-800 flex flex-col overflow-hidden flex-shrink-0">

                <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
                    <div>
                        <div class="text-sm font-bold text-indigo-300">CH{{ selectedCam.ch }}: {{ selectedCam.name }}</div>
                        <div class="text-xs text-gray-500 mt-0.5">歷史回放</div>
                    </div>
                    <button @click="selectedCam = null; playbackActive = false"
                            class="text-gray-600 hover:text-gray-400 text-xl leading-none">×</button>
                </div>

                <!-- Search controls -->
                <div class="px-4 py-3 border-b border-gray-800 space-y-3">
                    <div>
                        <label class="text-xs text-gray-400 block mb-1">查詢日期</label>
                        <input v-model="playbackDate" type="date"
                               class="w-full bg-gray-800 border border-gray-700 rounded p-2 text-white outline-none focus:border-indigo-500 text-sm">
                    </div>
                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="text-xs text-gray-400 block mb-1">開始</label>
                            <input v-model="playbackStart" type="time"
                                   class="w-full bg-gray-800 border border-gray-700 rounded p-2 text-white outline-none focus:border-indigo-500 text-sm">
                        </div>
                        <div>
                            <label class="text-xs text-gray-400 block mb-1">結束</label>
                            <input v-model="playbackEnd" type="time"
                                   class="w-full bg-gray-800 border border-gray-700 rounded p-2 text-white outline-none focus:border-indigo-500 text-sm">
                        </div>
                    </div>
                    <button @click="searchRecordings" :disabled="searchLoading"
                            class="w-full bg-indigo-700 hover:bg-indigo-600 disabled:bg-gray-700 text-white py-2 rounded text-sm font-bold transition-colors">
                        {{ searchLoading ? '搜尋中…' : '🔍 搜尋錄影' }}
                    </button>
                </div>

                <!-- Recording list -->
                <div class="flex-1 overflow-y-auto px-4 py-2">
                    <div v-if="recordings.length === 0 && !searchLoading" class="text-xs text-center text-gray-600 py-6">
                        選擇日期後點選搜尋
                    </div>
                    <div v-for="(rec, idx) in recordings" :key="idx"
                         class="mb-2 bg-gray-800 border border-gray-700 rounded-lg p-3 text-xs space-y-2">
                        <div class="text-gray-300 font-mono space-y-0.5">
                            <div>▶ {{ rec.StartTime || rec.BeginTime || rec.start_time || '—' }}</div>
                            <div>■ {{ rec.EndTime || rec.end_time || '—' }}</div>
                        </div>
                        <div class="flex gap-2">
                            <button @click="playRecording(rec)"
                                    class="flex-1 bg-indigo-800 hover:bg-indigo-700 text-white py-1.5 rounded font-bold transition-colors">
                                ▶ 播放
                            </button>
                            <button @click="downloadRec(rec, 'avi')"
                                    class="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-300 py-1.5 rounded font-bold transition-colors">
                                ⬇ AVI
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Playback stream -->
                <div v-if="playbackActive" class="border-t border-gray-800 p-3 flex-shrink-0">
                    <div class="text-xs text-indigo-400 font-bold mb-2 flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-indigo-400 animate-pulse"></span>
                        回放中 CH{{ selectedCam.ch }}
                    </div>
                    <div class="bg-black rounded overflow-hidden" style="aspect-ratio:16/9">
                        <img :src="playbackStreamUrl" class="w-full h-full object-contain"
                             @error="playbackError = true">
                        <div v-if="playbackError"
                             class="flex items-center justify-center h-full text-red-400 text-xs p-2 text-center">
                            串流載入失敗，請確認錄影時間與 NVR 連線
                        </div>
                    </div>
                    <button @click="playbackActive = false"
                            class="w-full mt-2 text-xs text-gray-600 hover:text-gray-400 py-1 border border-gray-800 hover:border-gray-700 rounded transition-colors">
                        停止回放
                    </button>
                </div>
            </div>

        </div>
    </div>
    `,
    setup() {
        const cameras      = ref([]);
        const gridCols     = ref(3);
        const selectedCam  = ref(null);
        const loadError    = ref('');
        const nvrInfo      = ref('');

        const playbackDate  = ref(new Date().toISOString().slice(0, 10));
        const playbackStart = ref('00:00');
        const playbackEnd   = ref('23:59');
        const recordings    = ref([]);
        const searchLoading = ref(false);
        const playbackActive = ref(false);
        const playbackStreamUrl = ref('');
        const playbackError = ref(false);

        const authHeaders = () => {
            const token = localStorage.getItem('mezzo_token');
            return token ? { 'Authorization': `Bearer ${token}` } : {};
        };

        const mjpegUrl = (ch) => {
            const token = localStorage.getItem('mezzo_token') || '';
            return `${BASE}/api/nvrv/mjpeg/${ch}?token=${token}`;
        };

        const snapshotUrl = (ch) => {
            const token = localStorage.getItem('mezzo_token') || '';
            return `${BASE}/api/nvrv/snapshot/${ch}?token=${token}`;
        };

        const loadCameras = async () => {
            cameras.value = [];
            loadError.value = '';
            try {
                const res = await store.authFetch(`${BASE}/api/nvrv/cameras`);
                if (!res.ok) {
                    loadError.value = `載入失敗 (${res.status})`;
                    return;
                }
                const data = await res.json();
                let list = [];
                if (Array.isArray(data)) {
                    list = data;
                } else if (data.Camera && Array.isArray(data.Camera)) {
                    list = data.Camera;
                } else if (data.cameras && Array.isArray(data.cameras)) {
                    list = data.cameras;
                } else if (typeof data === 'object') {
                    for (const k of Object.keys(data)) {
                        const v = data[k];
                        if (typeof v === 'object' && v !== null)
                            list.push({ ch: parseInt(k) || 0, ...v });
                    }
                }
                cameras.value = list.map((c, idx) => ({
                    ch:      c.Channel !== undefined ? Number(c.Channel) : c.ch !== undefined ? Number(c.ch) : idx,
                    name:    c.Name || c.name || c.CameraName || `Camera ${idx + 1}`,
                    enabled: c.Enable !== undefined ? !!c.Enable : true,
                    error:    false,
                    snapError: false
                }));
                const n = cameras.value.length;
                gridCols.value = n <= 4 ? 2 : n <= 9 ? 3 : 4;
            } catch (e) {
                loadError.value = `錯誤: ${e.message}`;
            }
        };

        const loadNvrInfo = async () => {
            try {
                const res = await store.authFetch(`${BASE}/api/nvrv/server_info`);
                if (res.ok) {
                    const d = await res.json();
                    const model = d.Model || d.model || '';
                    const ver   = d.Version ? 'v' + d.Version : '';
                    const host  = d.Hostname || d.hostname || '';
                    nvrInfo.value = [model, ver, host].filter(Boolean).join(' · ');
                }
            } catch (e) {}
        };

        const selectCamera = (cam) => {
            selectedCam.value = cam;
            recordings.value  = [];
            playbackActive.value = false;
        };

        const searchRecordings = async () => {
            if (!selectedCam.value || !playbackDate.value) return;
            searchLoading.value = true;
            recordings.value    = [];
            const begin = `${playbackDate.value} ${playbackStart.value}:00`;
            const end   = `${playbackDate.value} ${playbackEnd.value}:59`;
            try {
                const qs  = new URLSearchParams({ ch: selectedCam.value.ch, begin_time: begin, end_time: end });
                const res = await store.authFetch(`${BASE}/api/nvrv/recordings?${qs}`);
                if (!res.ok) return;
                const data = await res.json();
                if (Array.isArray(data))                    recordings.value = data;
                else if (data.Backup && Array.isArray(data.Backup)) recordings.value = data.Backup;
                else if (data.Record && Array.isArray(data.Record)) recordings.value = data.Record;
            } catch (e) {
                console.error('[NVRTab] searchRecordings error:', e);
            } finally {
                searchLoading.value = false;
            }
        };

        const playRecording = (rec) => {
            const timeStr = rec.StartTime || rec.BeginTime || rec.start_time || '';
            if (!timeStr || !selectedCam.value) return;
            const token = localStorage.getItem('mezzo_token') || '';
            const qs = new URLSearchParams({ time_str: timeStr, token });
            playbackStreamUrl.value = `${BASE}/api/nvrv/playback/${selectedCam.value.ch}?${qs}`;
            playbackError.value     = false;
            playbackActive.value    = true;
        };

        const downloadRec = (rec, fmt = 'avi') => {
            const tag = rec.Tag || rec.tag || rec.FileTag || '';
            if (!tag) { alert('找不到錄影 Tag'); return; }
            const token = localStorage.getItem('mezzo_token') || '';
            const qs = new URLSearchParams({ tag, fmt, token });
            window.open(`${BASE}/api/nvrv/download?${qs}`, '_blank');
        };

        onMounted(() => {
            loadCameras();
            loadNvrInfo();
        });

        return {
            store, cameras, gridCols, selectedCam, loadError, nvrInfo,
            playbackDate, playbackStart, playbackEnd,
            recordings, searchLoading,
            playbackActive, playbackStreamUrl, playbackError,
            mjpegUrl, snapshotUrl,
            loadCameras, selectCamera,
            searchRecordings, playRecording, downloadRec,
            BASE
        };
    }
};
