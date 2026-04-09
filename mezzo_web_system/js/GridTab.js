// js/GridTab.js
import { ref, onMounted, computed, watch, onUnmounted } from 'vue';
import { store, BASE } from './store.js';

export default {
    template: `
        <div class="w-full h-full flex flex-col bg-[#0f1115]">
            <div class="h-12 bg-gray-900 border-b border-gray-800 flex items-center px-4 justify-between z-10">
                <div class="text-blue-400 font-bold flex items-center gap-2">
                    <span>🎦 影像監控牆</span>
                    <span v-if="store.currentUser?.role === 'admin'" class="text-xs bg-red-900/50 text-red-400 px-2 py-1 rounded">NVR 直連模式啟用</span>
                </div>
                <div class="flex gap-2">
                    <span class="text-gray-400 text-sm mr-2 flex items-center">分割畫面設定:</span>
                    <button v-for="num in [1, 4, 9, 16, 32, 64]" :key="num" 
                            @click="changeLayout(num)" 
                            :class="layout === num ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'"
                            class="px-3 py-1 rounded text-xs font-bold transition-colors">
                        {{ num }}
                    </button>
                    <button @click="clearAll" class="ml-4 bg-red-900/50 hover:bg-red-800 text-red-400 px-3 py-1 rounded text-xs font-bold transition-colors">全部清除</button>
                </div>
            </div>

            <div class="flex-1 flex overflow-hidden">
                <div class="w-64 bg-gray-800 border-r border-gray-700 p-4 flex flex-col z-10">
                    
                    <h3 class="text-xs font-bold text-gray-300 mb-3 border-b border-gray-700 pb-2 flex justify-between items-center">
                        設備列表
                        <span v-if="store.currentUser?.role === 'admin'" 
                              @click="fetchNvrCameras" 
                              title="重新整理設備清單" 
                              class="text-gray-500 cursor-pointer hover:text-[#00f6ff] text-lg leading-none transition-colors">↻</span>
                    </h3>

                    <div class="flex-1 overflow-y-auto space-y-2 pr-1">
                        <div v-for="dev in store.devices" :key="dev.device_id" 
                             @click="assignDevice(dev)" 
                             :title="'即時影像連結: ' + dev.mjpeg_url"
                             class="p-2 bg-gray-900 rounded border border-gray-700 hover:border-blue-500 cursor-pointer flex justify-between items-center transition-colors">
                            <div>
                                <div class="text-sm font-bold text-gray-200">{{ dev.name }}</div>
                                <div class="text-[10px]" :class="store.telemetry[dev.device_id]?.status === '離線' ? 'text-red-400' : 'text-[#00f6ff]'">{{ store.telemetry[dev.device_id]?.status || '未知' }}</div>
                            </div>
                        </div>

                        <template v-if="store.currentUser?.role === 'admin'">
                            <div v-if="nvrCameras.length === 0" 
                                 class="text-xs text-center py-3 rounded border"
                                 :class="nvrLoadingStatus.includes('失敗') ? 'bg-red-900/30 text-red-400 border-red-800/50' : 'text-gray-500 border-transparent'">
                                 {{ nvrLoadingStatus }}
                            </div>
                            <div v-for="cam in nvrCameras" :key="'nvr_'+cam.channelID" 
                                 @click="assignDevice(cam)" 
                                 :title="'即時影像連結: ' + cam.mjpeg_url"
                                 class="p-2 bg-gray-900 rounded border border-gray-700 hover:border-blue-500 cursor-pointer flex justify-between items-center transition-colors">
                                <div>
                                    <div class="text-sm font-bold text-gray-200">{{ cam.name }}</div>
                                    <div class="text-[10px] text-[#00f6ff] font-mono">CH: {{ cam.channelID }}</div>
                                </div>
                            </div>
                        </template>
                    </div>

                </div>
                
                <div class="flex-1 p-2 bg-black grid gap-1 relative" :class="gridClass">
                    <div v-for="(cell, index) in gridCells" :key="'cell-'+layout+'-'+index+'-'+(cell?cell.device_id:'')" 
                         @click="selectedCell = index" 
                         @dblclick="toggleMaximize(index)"
                         :class="[
                             selectedCell === index ? 'border-[#00f6ff] shadow-[0_0_10px_rgba(0,246,255,0.6)]' : 'border-gray-800',
                             maximizedCell === index ? 'absolute inset-2 z-50 shadow-2xl' : 'relative',
                             maximizedCell !== null && maximizedCell !== index ? 'hidden' : 'flex'
                         ]" 
                         class="border-2 bg-gray-900 flex-col cursor-pointer overflow-hidden transition-all duration-200">
                        
                        <template v-if="cell">
                            <div class="bg-gray-800 px-2 py-1 flex justify-between items-center border-b border-gray-700 z-10 shrink-0">
                                <span class="text-[10px] font-bold text-[#00f6ff] truncate flex-1" :title="cell.name">{{ cell.name }}</span>
                                <div class="flex gap-2 items-center ml-2">
                                    <span v-if="maximizedCell === index" class="text-[10px] text-gray-400 bg-gray-900 px-1 rounded">雙擊縮小</span>
                                    <button v-if="cell.isNvr" @click.stop="openPlayback(cell)" class="text-[10px] bg-purple-700 hover:bg-purple-600 text-white px-1.5 rounded transition-colors" title="歷史回放">回放</button>
                                    <button @click.stop="clearCell(index)" class="text-[10px] text-red-400 hover:text-white bg-red-900/30 px-1.5 rounded transition-colors">✕</button>
                                </div>
                            </div>
                            <div class="flex-1 flex items-center justify-center relative bg-black overflow-hidden">
                                <img :src="cell.mjpeg_url" class="w-full h-full object-contain" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                                <div class="hidden flex-col items-center justify-center text-gray-600 text-xs absolute w-full h-full bg-gray-900 px-4 text-center">
                                    <span class="mb-1 font-bold text-gray-400">無法載入影像串流</span>
                                    <span class="font-mono text-[9px] text-gray-500 break-all">{{ cell.mjpeg_url }}</span>
                                </div>
                            </div>
                        </template>
                        <template v-else>
                            <div class="flex-1 flex items-center justify-center text-gray-800 text-xl font-bold opacity-30"> {{ index + 1 }} </div>
                        </template>
                    </div>
                </div>
            </div>

            <div v-if="showPlaybackModal" class="fixed inset-0 bg-black/85 z-[200] flex items-center justify-center backdrop-blur-sm">
                <div class="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-[1000px] flex flex-col overflow-hidden">
                    
                    <div class="bg-gray-800 p-4 border-b border-gray-700 flex justify-between items-center shrink-0">
                        <h2 class="text-lg font-bold text-purple-400">⏪ 歷史影像回放 - {{ pbCamera?.name }} (CH: {{ pbCamera?.channelID }})</h2>
                        <button @click="closePlayback" class="text-gray-400 hover:text-white text-xl transition-colors">✕</button>
                    </div>
                    
                    <div class="flex h-[500px]">
                        <div class="w-72 bg-gray-800/80 border-r border-gray-700 p-4 flex flex-col">
                            <h3 class="text-sm font-bold text-gray-300 mb-4 border-b border-gray-700 pb-2">📅 選擇錄影日期</h3>
                            
                            <div class="flex justify-between items-center mb-4">
                                <button @click="changeMonth(-1)" class="text-gray-400 hover:text-white px-2 py-1 bg-gray-900 rounded transition-colors">◀</button>
                                <span class="font-bold text-white">{{ currentYear }} 年 {{ currentMonth }} 月</span>
                                <button @click="changeMonth(1)" class="text-gray-400 hover:text-white px-2 py-1 bg-gray-900 rounded transition-colors">▶</button>
                            </div>
                            
                            <div class="grid grid-cols-7 gap-1 text-center text-xs mb-2">
                                <span class="text-gray-500">日</span><span class="text-gray-500">一</span><span class="text-gray-500">二</span><span class="text-gray-500">三</span><span class="text-gray-500">四</span><span class="text-gray-500">五</span><span class="text-gray-500">六</span>
                            </div>
                            <div class="grid grid-cols-7 gap-1 text-center flex-1">
                                <div v-for="blank in blankDays" :key="'blank-'+blank"></div>
                                <div v-for="day in daysInMonth" :key="day" 
                                     @click="selectDate(day)"
                                     :class="[
                                        'h-8 flex flex-col items-center justify-center rounded cursor-pointer transition-colors relative',
                                        pbSelectedDate === \`\${currentYear}-\${padZero(currentMonth)}-\${padZero(day)}\` ? 'bg-purple-600 text-white font-bold' : 'hover:bg-gray-700 text-gray-300',
                                     ]">
                                    <span class="z-10">{{ day }}</span>
                                    <div v-if="recordStatusArray[day-1] === '1'" class="absolute inset-1 bg-[#00f6ff]/30 rounded-full blur-[2px]"></div>
                                </div>
                            </div>
                            
                            <div class="mt-4 pt-4 border-t border-gray-700 text-xs text-gray-400 flex flex-col gap-2">
                                <div class="flex items-center gap-2"><div class="w-3 h-3 bg-[#00f6ff]/30 rounded-full"></div> 表示有錄影資料</div>
                                <button @click="downloadVideo" class="w-full mt-2 bg-[#00aaaa] hover:bg-[#00cccc] text-white py-2 rounded font-bold transition-colors">⬇ 下載當日錄影 (AVI)</button>
                            </div>
                        </div>

                        <div class="flex-1 flex flex-col bg-black">
                            <div class="flex-1 relative flex items-center justify-center">
                                <img v-if="pbStreamUrl" :src="pbStreamUrl" class="w-full h-full object-contain">
                                <div v-else class="text-gray-500 text-sm flex flex-col items-center">
                                    <span class="text-4xl mb-2">🎥</span>
                                    <span>請從左側日曆選擇有錄影檔案的日期</span>
                                </div>
                            </div>
                            
                            <div class="h-32 bg-gray-900 border-t border-gray-700 p-4 flex flex-col justify-between">
                                <div class="flex items-center gap-4 w-full">
                                    <span class="text-[#00f6ff] font-mono text-sm w-20 text-right">{{ formattedPbTime }}</span>
                                    <input type="range" min="0" max="86399" v-model="sliderValue" 
                                           @mousedown="isDragging = true" 
                                           @input="onSliderDrag"
                                           @change="onSliderDrop"
                                           class="flex-1 h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-[#00f6ff]">
                                    <span class="text-gray-500 font-mono text-sm w-20">23:59:59</span>
                                </div>
                                
                                <div class="flex items-center justify-center gap-6 mt-2 relative">
                                    <button @click="setDirection(-1)" :class="pbDir === -1 ? 'text-purple-400 bg-purple-900/30' : 'text-gray-400 hover:text-white'" class="px-3 py-1 rounded text-sm transition-colors" title="反向播放">⏪ 倒播</button>
                                    
                                    <button @click="togglePlayPause" class="w-12 h-12 bg-purple-600 hover:bg-purple-500 rounded-full flex items-center justify-center text-white text-xl shadow-[0_0_15px_rgba(147,51,234,0.5)] transition-all">
                                        <span v-if="pbStatus === 0">▶</span>
                                        <span v-else>⏸</span>
                                    </button>
                                    
                                    <button @click="stopPlayback" class="text-gray-400 hover:text-red-400 px-3 py-1 rounded text-sm transition-colors" title="停止播放">⏹ 停止</button>

                                    <div class="absolute right-0 flex items-center gap-2">
                                        <span class="text-xs text-gray-500">倍速</span>
                                        <select v-model="pbSpeed" @change="changeSpeed" class="bg-gray-800 text-white text-xs border border-gray-600 rounded px-2 py-1 outline-none focus:border-[#00f6ff]">
                                            <option :value="16">16x</option>
                                            <option :value="8">8x</option>
                                            <option :value="4">4x</option>
                                            <option :value="2">2x</option>
                                            <option :value="1">1x</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                </div>
            </div>
        </div>
    `,
    setup() {
        const NVR_IP = '118.163.141.80';
        const NVR_PORT = '80';
        const NVR_AUTH = 'YWRtaW46MTIzNA=='; 

        const layout = ref(9);
        const gridCells = ref(Array(9).fill(null));
        const selectedCell = ref(0);
        const nvrCameras = ref([]);
        const maximizedCell = ref(null); 
        const nvrLoadingStatus = ref('正在連線至 NVR...'); // 新增：用於顯示連線狀態與錯誤

        const showPlaybackModal = ref(false);
        const pbCamera = ref(null);
        const pbStreamUrl = ref('');
        const pbRoomId = ref('');
        
        const currentDateObj = ref(new Date());
        const currentYear = computed(() => currentDateObj.value.getFullYear());
        const currentMonth = computed(() => currentDateObj.value.getMonth() + 1);
        const blankDays = computed(() => new Date(currentYear.value, currentMonth.value - 1, 1).getDay());
        const daysInMonth = computed(() => new Date(currentYear.value, currentMonth.value, 0).getDate());
        const recordStatusArray = ref(Array(31).fill('0')); 
        const pbSelectedDate = ref(''); 
        
        const pbStatus = ref(-1); 
        const pbSpeed = ref(1);   
        const pbDir = ref(1);     
        
        const sliderValue = ref(0); 
        const isDragging = ref(false);
        let pollingInterval = null;

        const padZero = (num) => num.toString().padStart(2, '0');

        const formattedPbTime = computed(() => {
            const h = Math.floor(sliderValue.value / 3600);
            const m = Math.floor((sliderValue.value % 3600) / 60);
            const s = sliderValue.value % 60;
            return `${padZero(h)}:${padZero(m)}:${padZero(s)}`;
        });

        const gridClass = computed(() => {
            switch(layout.value) { case 1: return 'grid-cols-1 grid-rows-1'; case 4: return 'grid-cols-2 grid-rows-2'; case 9: return 'grid-cols-3 grid-rows-3'; case 16: return 'grid-cols-4 grid-rows-4'; case 32: return 'grid-cols-8 grid-rows-4'; case 64: return 'grid-cols-8 grid-rows-8'; default: return 'grid-cols-3 grid-rows-3'; }
        });
        const changeLayout = (num) => { layout.value = num; maximizedCell.value = null; const old = gridCells.value; gridCells.value = Array(num).fill(null).map((_, i) => old[i] || null); if (selectedCell.value >= num) selectedCell.value = 0; };
        const toggleMaximize = (index) => { if (!gridCells.value[index]) return; maximizedCell.value = maximizedCell.value === index ? null : index; };
        const clearAll = () => { gridCells.value = Array(layout.value).fill(null); maximizedCell.value = null; };
        const clearCell = (index) => { gridCells.value[index] = null; if (maximizedCell.value === index) maximizedCell.value = null; };

        const fetchNvrCameras = async () => {
            if (store.currentUser?.role !== 'admin') return;
            
            nvrLoadingStatus.value = '正在連線至 NVR...';
            nvrCameras.value = [];
            
            try {
                const res = await fetch(`${BASE}/api/nvr/cameras`);
                if (!res.ok) throw new Error("Proxy fetch failed");
                const data = await res.json();
                
                if (data && data.length > 0) {
                    nvrCameras.value = data.map(c => ({
                        device_id: `NVR_CH${c.channelID}`, name: c.desc || `Camera ${c.channelID}`, channelID: c.channelID, isNvr: true,
                        mjpeg_url: `http://${NVR_IP}:${NVR_PORT}/mjpeg_stream.cgi?Auth=${NVR_AUTH}&ch=${c.channelID}`
                    }));
                } else {
                    nvrLoadingStatus.value = 'NVR 系統內無設備資料';
                }
            } catch (e) {
                console.error("NVR Proxy 連線異常:", e);
                nvrLoadingStatus.value = '連線失敗，請確認後端或網路';
            }
        };

        const assignDevice = (dev) => {
            const deviceToAssign = { ...dev };
            if (!deviceToAssign.isNvr && (!deviceToAssign.mjpeg_url || deviceToAssign.mjpeg_url === 'http://')) deviceToAssign.mjpeg_url = "https://baconmockup.com/640/360";
            gridCells.value[selectedCell.value] = deviceToAssign;
            const nextEmpty = gridCells.value.findIndex(c => c === null);
            if(nextEmpty !== -1) selectedCell.value = nextEmpty;
        };

        const openPlayback = (cam) => {
            pbCamera.value = cam;
            pbStreamUrl.value = '';
            pbRoomId.value = crypto.randomUUID(); 
            sliderValue.value = 0;
            pbStatus.value = -1;
            pbSelectedDate.value = '';
            showPlaybackModal.value = true;
            
            currentDateObj.value = new Date();
            fetchMonthRecordStatus();
        };

        const closePlayback = () => {
            stopPlayback();
            showPlaybackModal.value = false;
        };

        const changeMonth = (offset) => {
            currentDateObj.value = new Date(currentYear.value, currentMonth.value - 1 + offset, 1);
            fetchMonthRecordStatus();
        };

        const fetchMonthRecordStatus = async () => {
            try {
                const searchTime = `${currentYear.value}-${padZero(currentMonth.value)}-01 00:00:00`;
                const url = `${BASE}/api/nvr/record_status?channel=${pbCamera.value.channelID}&time_str=${encodeURIComponent(searchTime)}`;
                const res = await fetch(url);
                const data = await res.json();
                
                if (data && data.status_array) {
                    recordStatusArray.value = data.status_array;
                } else {
                    recordStatusArray.value = Array(31).fill('0');
                }
            } catch (error) {
                console.warn("無法取得日曆錄影狀態 (Proxy Error)", error);
                recordStatusArray.value = Array(31).fill('0');
            }
        };

        const selectDate = async (day) => {
            if (recordStatusArray.value[day-1] === '0') {
                alert("該日期無錄影資料"); return;
            }
            pbSelectedDate.value = `${currentYear.value}-${padZero(currentMonth.value)}-${padZero(day)}`;
            sliderValue.value = 0; 
            
            await initPlaybackRoom();
        };

        const sendControlCmd = async (cmd, status, timeStr = "") => {
            try {
                await fetch(`http://${NVR_IP}:${NVR_PORT}/mjpeg_playback_control.cgi?Auth=${NVR_AUTH}`, {
                    method: 'POST',
                    body: JSON.stringify({ 
                        room_id: pbRoomId.value, 
                        cmd: cmd, 
                        status: status, 
                        time: timeStr, 
                        speed: pbSpeed.value, 
                        dir: pbDir.value 
                    })
                });
            } catch (e) {
                console.error("Playback control error", e);
            }
        };

        const initPlaybackRoom = async () => {
            stopPolling();
            const startTimeStr = `${pbSelectedDate.value} 00:00:00`;
            
            await sendControlCmd(1, 0); 
            pbStatus.value = 1;
            await sendControlCmd(2, 1, startTimeStr); 
            
            pbStreamUrl.value = `http://${NVR_IP}:${NVR_PORT}/mjpeg_stream.cgi?Auth=${NVR_AUTH}&ch=${pbCamera.value.channelID}&clientid=1&roomId=${pbRoomId.value}`;
            
            startPolling();
        };

        const togglePlayPause = async () => {
            if (!pbSelectedDate.value) return;
            pbStatus.value = pbStatus.value === 1 ? 0 : 1; 
            await sendControlCmd(2, pbStatus.value);
        };

        const stopPlayback = async () => {
            if (!pbSelectedDate.value) return;
            pbStatus.value = -1;
            pbStreamUrl.value = '';
            stopPolling();
            await sendControlCmd(2, -1); 
        };

        const changeSpeed = async () => {
            if (pbStatus.value === 1) await sendControlCmd(2, 1);
        };

        const setDirection = async (dir) => {
            if (!pbSelectedDate.value) return;
            pbDir.value = dir;
            if (pbStatus.value === 1) await sendControlCmd(2, 1); 
        };

        const onSliderDrag = () => {
            isDragging.value = true; 
        };

        const onSliderDrop = async () => {
            if (!pbSelectedDate.value) return;
            const seekTimeStr = `${pbSelectedDate.value} ${formattedPbTime.value}`;
            pbStatus.value = 1; 
            await sendControlCmd(2, 1, seekTimeStr);
            isDragging.value = false;
        };

        const pollPlaybackStatus = async () => {
            if (isDragging.value || pbStatus.value !== 1) return;
            try {
                const res = await fetch(`http://${NVR_IP}:${NVR_PORT}/mjpeg_playback_control.cgi?Auth=${NVR_AUTH}`, {
                    method: 'POST',
                    body: JSON.stringify({ room_id: pbRoomId.value, cmd: 0 })
                });
                const data = await res.json();
                
                if (data && data[0] && data[0].data && data[0].data.frame_time) {
                    const fTime = data[0].data.frame_time;
                    const timePart = fTime.split(' ')[1]; 
                    if (timePart) {
                        const [h, m, s] = timePart.split(':').map(Number);
                        sliderValue.value = (h * 3600) + (m * 60) + s;
                    }
                }
            } catch (e) {}
        };

        const startPolling = () => {
            if (pollingInterval) clearInterval(pollingInterval);
            pollingInterval = setInterval(pollPlaybackStatus, 1000);
        };

        const stopPolling = () => {
            if (pollingInterval) clearInterval(pollingInterval);
        };

        onUnmounted(() => {
            stopPolling();
        });

        const downloadVideo = async () => {
            if (!pbSelectedDate.value) return alert("請先選擇要下載的日期");
            
            const bTime = `${pbSelectedDate.value} 00:00:00`;
            const eTime = `${pbSelectedDate.value} 23:59:59`; 
            const ch = pbCamera.value.channelID;

            try {
                const listUrl = `http://${NVR_IP}:${NVR_PORT}/GetBackupList.cgi?BeginTime=${encodeURIComponent(bTime)}&EndTime=${encodeURIComponent(eTime)}&Channels=${ch}&Auth=${NVR_AUTH}`;
                const listRes = await fetch(listUrl);
                const listData = await listRes.json();

                if (listData?.data?.[0]?.FileList?.length > 0) {
                    const tag = listData.data[0].FileList[0].Tag; 
                    const dlUrl = `http://${NVR_IP}:${NVR_PORT}/GetAVIMedia.cgi?Tag=${tag}&Auth=${NVR_AUTH}`;
                    window.open(dlUrl, '_blank'); 
                } else {
                    alert("該日期內無錄影資料可供下載");
                }
            } catch (error) {
                alert("無法取得檔案清單");
            }
        };

        onMounted(() => {
            fetchNvrCameras();
        });

        return { 
            store, layout, gridClass, gridCells, selectedCell, maximizedCell, nvrLoadingStatus,
            changeLayout, clearAll, clearCell, toggleMaximize, nvrCameras, fetchNvrCameras, assignDevice,
            
            showPlaybackModal, pbCamera, pbStreamUrl, 
            currentYear, currentMonth, daysInMonth, blankDays, recordStatusArray, pbSelectedDate,
            pbStatus, pbSpeed, pbDir, sliderValue, formattedPbTime, isDragging,
            
            openPlayback, closePlayback, changeMonth, selectDate,
            togglePlayPause, stopPlayback, changeSpeed, setDirection, onSliderDrag, onSliderDrop,
            downloadVideo, padZero
        };
    }
};