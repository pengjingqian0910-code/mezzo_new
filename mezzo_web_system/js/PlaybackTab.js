// js/PlaybackTab.js
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { store } from './store.js';

export default {
    template: `
        <div class="w-full h-full flex relative bg-[#0f1115]">

            <div class="w-80 bg-gray-900 border-r border-gray-800 flex flex-col z-20 shadow-2xl">
                <div class="p-4 border-b border-gray-800 shrink-0">
                    <h2 class="text-lg font-bold text-purple-400">🗺️ 軌跡與影像回放</h2>
                    <p class="text-xs text-gray-500 mt-1">整合 NVR 錄影 / GPS / 語音 同步分析</p>
                </div>

                <div class="flex-1 overflow-y-auto flex flex-col">
                    <!-- 1. 選擇設備 -->
                    <div class="p-4 border-b border-gray-800 shrink-0">
                        <h3 class="text-xs font-bold text-gray-400 mb-3 border-b border-gray-700 pb-1">1. 選擇調閱設備</h3>
                        <div class="max-h-40 overflow-y-auto pr-1 space-y-2">
                            <div v-for="dev in store.devices" :key="dev.device_id"
                                 @click="selectDevice(dev)"
                                 :class="selectedDevice?.device_id === dev.device_id ? 'bg-purple-900 border-purple-500' : 'bg-gray-800 border-gray-700 hover:border-purple-400'"
                                 class="p-2 rounded border cursor-pointer transition-colors flex justify-between items-center">
                                <div class="text-sm font-bold text-gray-200">{{ dev.name }}</div>
                                <div class="text-[10px] text-gray-400 font-mono">{{ dev.device_id }}</div>
                            </div>
                        </div>
                    </div>

                    <div v-if="selectedDevice" class="p-4 flex-1 flex flex-col">
                        <!-- 2. 選擇日期 -->
                        <h3 class="text-xs font-bold text-gray-400 mb-3 border-b border-gray-700 pb-1">2. 選擇錄影日期</h3>

                        <div class="flex justify-between items-center mb-4">
                            <button @click="changeMonth(-1)" class="text-gray-400 hover:text-white px-2 py-1 bg-gray-800 rounded">◀</button>
                            <span class="font-bold text-white text-sm">{{ currentYear }} 年 {{ currentMonth }} 月</span>
                            <button @click="changeMonth(1)" class="text-gray-400 hover:text-white px-2 py-1 bg-gray-800 rounded">▶</button>
                        </div>

                        <div class="grid grid-cols-7 gap-1 text-center text-xs mb-2 shrink-0">
                            <span class="text-gray-500">日</span><span class="text-gray-500">一</span><span class="text-gray-500">二</span><span class="text-gray-500">三</span><span class="text-gray-500">四</span><span class="text-gray-500">五</span><span class="text-gray-500">六</span>
                        </div>
                        <div class="grid grid-cols-7 gap-1 text-center shrink-0">
                            <div v-for="blank in blankDays" :key="'blank-'+blank"></div>
                            <div v-for="day in daysInMonth" :key="day"
                                 @click="selectDate(day)"
                                 :class="[
                                    'h-8 flex flex-col items-center justify-center rounded cursor-pointer transition-colors relative',
                                    pbSelectedDate === \`\${currentYear}-\${padZero(currentMonth)}-\${padZero(day)}\` ? 'bg-purple-600 text-white font-bold' : 'hover:bg-gray-700 text-gray-300 bg-gray-800',
                                 ]">
                                <span class="z-10">{{ day }}</span>
                                <div v-if="recordStatusArray[day-1] === '1'" class="absolute inset-1 bg-blue-500/30 rounded-full blur-[2px]"></div>
                            </div>
                        </div>

                        <!-- 3. 錄影檔清單 -->
                        <div v-if="pbSelectedDate" class="mt-4 pt-4 border-t border-gray-700 flex flex-col gap-2">
                            <div class="text-xs font-bold text-gray-400 mb-1">3. 錄影檔清單 ({{ pbSelectedDate }})</div>

                            <div v-if="isLoadingFiles" class="text-xs text-gray-500 text-center py-2 animate-pulse">查詢 NVR 中...</div>
                            <div v-else-if="fileList.length === 0" class="text-xs text-gray-500 text-center py-2">該日無錄影資料</div>

                            <div v-for="(f, idx) in fileList" :key="f.Tag"
                                 @click="selectFile(f)"
                                 :class="selectedFile?.Tag === f.Tag ? 'border-purple-500 bg-purple-900/30' : 'border-gray-700 bg-gray-800 hover:border-purple-400'"
                                 class="p-2 rounded border cursor-pointer transition-colors text-xs">
                                <div class="text-gray-200 font-bold mb-1">片段 {{ idx+1 }}</div>
                                <div class="text-gray-400 font-mono">{{ f.BeginTime }} → {{ f.EndTime }}</div>
                                <div class="flex gap-2 mt-2">
                                    <button @click.stop="downloadAvi(f.Tag)" class="flex-1 bg-green-800 hover:bg-green-700 text-white py-1 rounded text-[10px] font-bold">⬇ AVI</button>
                                    <button @click.stop="downloadRaw(f.Tag)" class="flex-1 bg-blue-800 hover:bg-blue-700 text-white py-1 rounded text-[10px] font-bold">⬇ RAW</button>
                                </div>
                            </div>
                        </div>

                        <!-- 4. 歷史音檔 -->
                        <div v-if="pbSelectedDate && audioFiles.length > 0" class="mt-3 pt-3 border-t border-gray-700">
                            <div class="text-xs font-bold text-gray-400 mb-2">4. 歷史音檔 ({{ audioFiles.length }} 筆)</div>
                            <div v-for="af in audioFiles" :key="af.filename" class="mb-2 bg-gray-800 p-2 rounded border border-gray-700">
                                <div class="text-[10px] text-gray-400 mb-1 font-mono">{{ af.filename }}</div>
                                <audio :src="af.url" controls class="w-full h-8 outline-none"></audio>
                            </div>
                        </div>

                        <div class="mt-3 flex items-center gap-2 text-[10px] text-gray-500">
                            <div class="w-3 h-3 bg-blue-500/30 rounded-full"></div> 藍色日期表示當天有 NVR 錄影
                        </div>
                    </div>
                </div>
            </div>

            <!-- 主畫面：地圖 + 影片 -->
            <div class="flex-1 relative flex flex-col bg-black">

                <div class="flex-1 relative">
                    <div id="playbackCesiumContainer" class="w-full h-full"></div>

                    <div v-if="!selectedFile" class="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
                        <div class="bg-gray-900/80 backdrop-blur border border-gray-700 px-6 py-4 rounded-xl text-gray-400 font-bold tracking-widest shadow-2xl">
                            請從左側選擇設備 → 日期 → 錄影片段
                        </div>
                    </div>

                    <!-- 影片播放器 -->
                    <div v-show="selectedFile" class="absolute top-4 right-4 w-[400px] bg-black border-2 border-gray-700 rounded-xl shadow-2xl overflow-hidden z-20">
                        <div class="bg-gray-800 px-3 py-2 flex justify-between items-center border-b border-gray-700">
                            <span class="text-xs font-bold text-purple-400">
                                執法儀視角 ({{ selectedDevice?.device_id }})
                            </span>
                            <span class="text-[10px] text-gray-400 font-mono" v-if="selectedFile">{{ selectedFile.BeginTime }}</span>
                        </div>
                        <div class="aspect-video bg-gray-900">
                            <div v-if="useStreamPlayback" class="w-full h-full">
                                <img :src="mjpegStreamSrc" alt="MJPEG Stream" class="w-full h-full object-contain">
                            </div>
                            <video v-else
                                   ref="videoPlayer"
                                   :src="videoSrc"
                                   @timeupdate="onTimeUpdate"
                                   @loadedmetadata="onVideoLoaded"
                                   @ended="isPlaying = false"
                                   class="w-full h-full object-contain">
                            </video>
                        </div>
                    </div>

                    <!-- GPS 狀態提示 -->
                    <div v-show="selectedFile" class="absolute bottom-4 right-4 w-[400px] bg-gray-900/90 backdrop-blur-md border-2 border-gray-700 rounded-xl shadow-2xl p-4 z-20">
                        <div class="text-xs font-bold text-blue-400 mb-2">📍 GPS 位置</div>
                        <div v-if="currentGps" class="font-mono text-xs text-gray-300 space-y-1">
                            <div>Lat: {{ currentGps.lat.toFixed(6) }}</div>
                            <div>Lng: {{ currentGps.lng.toFixed(6) }}</div>
                            <div class="text-gray-500 text-[10px]">（MQTT 最後已知位置）</div>
                        </div>
                        <div v-else class="text-xs text-gray-500">尚無 GPS 資料（等待 MQTT 即時更新）</div>
                    </div>
                </div>

                <!-- 播放控制列 -->
                <div class="h-20 bg-gray-900 border-t border-gray-800 flex items-center px-6 gap-6 z-20 shrink-0">
                    <button @click="togglePlay" :disabled="!selectedFile"
                            class="w-12 h-12 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 rounded-full flex items-center justify-center text-white text-xl transition-all">
                        <span v-if="!isPlaying">▶</span>
                        <span v-else>⏸</span>
                    </button>

                    <div class="flex-1 flex items-center gap-4">
                        <span class="text-purple-400 font-mono text-sm w-16 text-right">{{ formattedCurrentTime }}</span>
                        <div class="flex-1 relative flex items-center">
                            <div class="absolute w-full h-2 bg-gray-800 rounded-lg pointer-events-none"></div>
                            <input type="range" min="0" :max="duration" step="0.1" v-model="currentTime"
                                   @input="onSliderInput" @change="onSliderChange"
                                   :disabled="!selectedFile"
                                   class="w-full h-2 bg-transparent rounded-lg appearance-none cursor-pointer accent-purple-500 z-10 relative">
                        </div>
                        <span class="text-gray-500 font-mono text-sm w-16">{{ formattedDuration }}</span>
                    </div>

                    <div v-if="selectedFile" class="text-[10px] text-gray-500 border-l border-gray-700 pl-4 shrink-0">
                        <div class="text-gray-400 font-bold">{{ selectedFile.BeginTime }}</div>
                        <div class="text-gray-500">→ {{ selectedFile.EndTime }}</div>
                    </div>
                </div>
            </div>
        </div>
    `,
    setup() {
        const selectedDevice  = ref(null);
        const selectedFile    = ref(null);
        const fileList        = ref([]);
        const audioFiles      = ref([]);
        const isLoadingFiles  = ref(false);
        const videoSrc        = ref('');
        const mjpegStreamSrc  = ref('');
        const useStreamPlayback = ref(false);  // true = MJPEG stream, false = downloaded video

        const currentDateObj  = ref(new Date());
        const currentYear     = computed(() => currentDateObj.value.getFullYear());
        const currentMonth    = computed(() => currentDateObj.value.getMonth() + 1);
        const blankDays       = computed(() => new Date(currentYear.value, currentMonth.value - 1, 1).getDay());
        const daysInMonth     = computed(() => new Date(currentYear.value, currentMonth.value, 0).getDate());
        const recordStatusArray = ref(Array(31).fill('0'));
        const pbSelectedDate  = ref('');

        const videoPlayer  = ref(null);
        const isPlaying    = ref(false);
        const currentTime  = ref(0);
        const duration     = ref(0);
        const isDragging   = ref(false);
        const currentGps   = ref(null);

        let viewer = null;

        const padZero = (n) => n.toString().padStart(2, '0');
        const formatTime = (s) => {
            const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
            return `${padZero(h)}:${padZero(m)}:${padZero(sec)}`;
        };
        const formattedCurrentTime = computed(() => formatTime(currentTime.value));
        const formattedDuration    = computed(() => formatTime(duration.value));

        // ====== 地圖初始化 ======
        const initMap = () => {
            if (viewer) return;
            viewer = new Cesium.Viewer('playbackCesiumContainer', {
                baseLayerPicker: false, imageryProvider: false, geocoder: false,
                homeButton: false, infoBox: false, navigationHelpButton: false,
                sceneModePicker: false, timeline: false, animation: false, selectionIndicator: false
            });
            viewer.imageryLayers.addImageryProvider(
                new Cesium.UrlTemplateImageryProvider({ url: 'https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}' })
            );
            viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(121.5644, 25.033, 8000) });
        };

        // ====== 選擇設備 ======
        const selectDevice = (dev) => {
            selectedDevice.value = dev;
            pbSelectedDate.value = '';
            fileList.value = [];
            audioFiles.value = [];
            selectedFile.value = null;
            videoSrc.value = '';
            mjpegStreamSrc.value = '';
            useStreamPlayback.value = false;
            currentDateObj.value = new Date();

            // 顯示該設備的最後已知 GPS 位置
            const pos = store.telemetry[dev.device_id];
            if (pos) {
                currentGps.value = pos;
                if (viewer) viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(pos.lng, pos.lat, 1500) });
            }
            fetchMonthRecordStatus();
        };

        const changeMonth = (offset) => {
            currentDateObj.value = new Date(currentYear.value, currentMonth.value - 1 + offset, 1);
            if (selectedDevice.value) fetchMonthRecordStatus();
        };

        // ====== 查詢月份錄影狀態 ======
        const fetchMonthRecordStatus = async () => {
            if (!selectedDevice.value) return;
            recordStatusArray.value = Array(31).fill('0');
            try {
                let channel = 0;
                if (selectedDevice.value.device_id.startsWith('NVR_CH')) {
                    channel = parseInt(selectedDevice.value.device_id.replace('NVR_CH', ''));
                }
                const searchTime = `${currentYear.value}-${padZero(currentMonth.value)}-01 00:00:00`;
                const res = await fetch(`/api/nvr/record_status?channel=${channel}&time_str=${encodeURIComponent(searchTime)}`);
                const data = await res.json();
                if (data?.status_array) recordStatusArray.value = data.status_array;
            } catch (e) {
                console.error('[Playback] fetchMonthRecordStatus error', e);
            }
        };

        // ====== 選擇日期：查詢 NVR 錄影清單 + 音檔 ======
        const selectDate = async (day) => {
            pbSelectedDate.value = `${currentYear.value}-${padZero(currentMonth.value)}-${padZero(day)}`;
            selectedFile.value = null;
            videoSrc.value = '';
            mjpegStreamSrc.value = '';
            useStreamPlayback.value = false;
            fileList.value = [];
            audioFiles.value = [];
            isLoadingFiles.value = true;

            try {
                let channel = 0;
                if (selectedDevice.value.device_id.startsWith('NVR_CH')) {
                    channel = parseInt(selectedDevice.value.device_id.replace('NVR_CH', ''));
                }
                const beginTime = `${pbSelectedDate.value} 00:00:00`;
                const endTime   = `${pbSelectedDate.value} 23:59:59`;
                const params = new URLSearchParams({ channels: channel, begin_time: beginTime, end_time: endTime });
                const res  = await fetch(`/api/nvr/history?${params}`);
                const data = await res.json();

                if (data?.success && data.data) {
                    fileList.value = data.data.flatMap(ch =>
                        (ch.FileList || []).map(f => ({
                            Tag: f.Tag, BeginTime: f.BeginTime, EndTime: f.EndTime,
                            Channel: ch.Ch, FileName: f.FileName
                        }))
                    );
                }
            } catch (e) {
                console.error('[Playback] NVR history error', e);
            } finally {
                isLoadingFiles.value = false;
            }

            // 同步查詢音檔列表
            try {
                const audioRes = await fetch(`/api/audio/${selectedDevice.value.device_id}`);
                const allAudio = await audioRes.json();
                // 篩選當日的音檔（依檔名前綴含日期字串）
                const dateStr = pbSelectedDate.value.replace(/-/g, '');
                audioFiles.value = allAudio.filter(a => a.filename.includes(dateStr));
            } catch (e) { /* 無音檔目錄時略過 */ }
        };

        // ====== 選擇錄影片段 ======
        const selectFile = (f) => {
            selectedFile.value = f;
            isPlaying.value = false;
            currentTime.value = 0;
            duration.value = 0;

            // 優先使用 MJPEG 串流回放（實時按需解碼），失敗時降級至下載 AVI
            let channel = 0;
            if (selectedDevice.value.device_id.startsWith('NVR_CH')) {
                channel = parseInt(selectedDevice.value.device_id.replace('NVR_CH', ''));
            }

            // 嘗試 MJPEG 流回放
            mjpegStreamSrc.value = `/api/nvr/playback_stream/${channel}?time=${encodeURIComponent(f.BeginTime)}`;
            useStreamPlayback.value = true;

            // 同時也保留 AVI 下載作為備用
            videoSrc.value = `/api/nvr/download/avi?tag=${encodeURIComponent(f.Tag)}`;
        };

        // ====== 下載 ======
        const downloadAvi = (tag) => window.open(`/api/nvr/download/avi?tag=${encodeURIComponent(tag)}`, '_blank');
        const downloadRaw = (tag) => window.open(`/api/nvr/download/raw?tag=${encodeURIComponent(tag)}`, '_blank');

        // ====== 播放控制 ======
        const togglePlay = () => {
            if (!videoPlayer.value || useStreamPlayback.value) return;  // MJPEG 流自動播放
            if (isPlaying.value) { videoPlayer.value.pause(); }
            else { videoPlayer.value.play(); }
            isPlaying.value = !isPlaying.value;
        };

        const onVideoLoaded = () => { duration.value = videoPlayer.value?.duration || 0; };

        const onTimeUpdate = () => {
            if (isDragging.value || useStreamPlayback.value) return;
            currentTime.value = videoPlayer.value?.currentTime || 0;
        };

        const onSliderInput = (e) => {
            isDragging.value = true;
            currentTime.value = parseFloat(e.target.value);
        };

        const onSliderChange = (e) => {
            isDragging.value = false;
            if (videoPlayer.value && !useStreamPlayback.value) videoPlayer.value.currentTime = parseFloat(e.target.value);
        };

        onMounted(() => { setTimeout(initMap, 100); });
        onUnmounted(() => { if (viewer) viewer.destroy(); });

        return {
            store, selectedDevice, selectedFile, fileList, audioFiles,
            isLoadingFiles, videoSrc, mjpegStreamSrc, useStreamPlayback, videoPlayer, currentGps,
            currentYear, currentMonth, daysInMonth, blankDays,
            recordStatusArray, pbSelectedDate,
            isPlaying, currentTime, duration,
            formattedCurrentTime, formattedDuration,
            padZero, selectDevice, changeMonth, selectDate, selectFile,
            downloadAvi, downloadRaw, togglePlay,
            onTimeUpdate, onVideoLoaded, onSliderInput, onSliderChange
        };
    }
};
