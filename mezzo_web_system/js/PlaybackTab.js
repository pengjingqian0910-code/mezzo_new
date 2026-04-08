// js/PlaybackTab.js
import { ref, computed } from 'vue';

export default {
    template: `
        <div class="w-full h-full flex flex-col bg-[#0f1115] text-gray-200">

            <!-- 查詢列 -->
            <div class="bg-gray-900 border-b border-gray-800 p-4 flex flex-wrap gap-4 items-end shrink-0">
                <h2 class="w-full text-base font-bold text-purple-400 mb-1">錄影查詢</h2>

                <div class="flex flex-col gap-1">
                    <label class="text-xs text-gray-400">起始時間</label>
                    <input type="datetime-local" v-model="startTime"
                           class="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-purple-500" />
                </div>

                <div class="flex flex-col gap-1">
                    <label class="text-xs text-gray-400">結束時間</label>
                    <input type="datetime-local" v-model="endTime"
                           class="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-purple-500" />
                </div>

                <div class="flex flex-col gap-1">
                    <label class="text-xs text-gray-400">頻道</label>
                    <select v-model="channel"
                            class="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-purple-500">
                        <option v-for="n in 12" :key="n-1" :value="n-1">頻道 {{ n-1 }}</option>
                    </select>
                </div>

                <button @click="search" :disabled="!canSearch || loading"
                        class="px-5 py-2 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 rounded font-bold text-sm transition-colors">
                    {{ loading ? '查詢中...' : '查詢錄影' }}
                </button>
            </div>

            <!-- 錯誤訊息 -->
            <div v-if="error" class="mx-4 mt-3 bg-red-900/40 border border-red-700 rounded p-3 text-red-400 text-sm shrink-0">
                {{ error }}
            </div>

            <!-- 結果 + 播放區 -->
            <div class="flex-1 flex min-h-0">

                <!-- 左側：錄影清單 -->
                <div class="w-80 border-r border-gray-800 flex flex-col">
                    <div class="p-3 border-b border-gray-800 text-xs text-gray-500 shrink-0">
                        <span v-if="results.length > 0">共 {{ results.length }} 筆錄影</span>
                        <span v-else-if="!loading">請輸入時間範圍後查詢</span>
                    </div>

                    <div class="flex-1 overflow-y-auto p-2 space-y-2">
                        <div v-if="loading" class="text-center py-8 text-gray-500 text-sm animate-pulse">查詢 NVR 中...</div>

                        <div v-for="(item, idx) in results" :key="item.Tag"
                             @click="selectFile(item)"
                             :class="selectedFile?.Tag === item.Tag
                                ? 'border-purple-500 bg-purple-900/30'
                                : 'border-gray-700 bg-gray-800 hover:border-purple-500'"
                             class="p-3 rounded border cursor-pointer transition-colors">
                            <div class="flex justify-between items-center mb-1">
                                <span class="text-xs font-bold text-purple-400">片段 {{ idx + 1 }}</span>
                                <span class="text-[10px] text-gray-500 font-mono">CH{{ item.Channel }}</span>
                            </div>
                            <div class="text-[11px] text-gray-300 font-mono">{{ item.BeginTime }}</div>
                            <div class="text-[11px] text-gray-500 font-mono">→ {{ item.EndTime }}</div>
                            <div class="flex gap-2 mt-2">
                                <button @click.stop="downloadAvi(item.Tag)"
                                        class="flex-1 bg-green-800 hover:bg-green-700 text-white text-[10px] py-1 rounded font-bold">
                                    ⬇ AVI
                                </button>
                                <button @click.stop="downloadRaw(item.Tag)"
                                        class="flex-1 bg-blue-800 hover:bg-blue-700 text-white text-[10px] py-1 rounded font-bold">
                                    ⬇ RAW
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 右側：影片播放 -->
                <div class="flex-1 flex flex-col items-center justify-center bg-black relative">
                    <div v-if="!selectedFile" class="text-gray-600 text-sm font-bold tracking-widest">
                        選擇左側錄影片段以播放
                    </div>

                    <div v-if="selectedFile" class="w-full h-full flex flex-col">
                        <!-- 影片標題 -->
                        <div class="bg-gray-900 px-4 py-2 flex justify-between items-center border-b border-gray-800 shrink-0">
                            <span class="text-xs font-bold text-purple-400">
                                CH{{ selectedFile.Channel }} — {{ selectedFile.BeginTime }} → {{ selectedFile.EndTime }}
                            </span>
                            <button @click="toggleMode"
                                    class="text-[10px] px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-gray-300">
                                {{ useStream ? '切換下載模式' : '切換串流模式' }}
                            </button>
                        </div>

                        <!-- MJPEG 串流 -->
                        <div v-if="useStream" class="flex-1 flex items-center justify-center bg-black">
                            <img :src="streamSrc" class="max-w-full max-h-full object-contain"
                                 @error="onStreamError" />
                            <div v-if="streamError" class="absolute text-red-400 text-sm text-center px-8">
                                串流無法播放：{{ streamError }}<br>
                                <button @click="useStream = false" class="mt-2 text-xs underline text-blue-400">切換為下載模式</button>
                            </div>
                        </div>

                        <!-- 下載後播放 -->
                        <video v-else
                               :src="videoSrc"
                               controls
                               class="flex-1 w-full bg-black object-contain">
                        </video>
                    </div>
                </div>
            </div>
        </div>
    `,
    setup() {
        const startTime   = ref('');
        const endTime     = ref('');
        const channel     = ref(0);
        const loading     = ref(false);
        const error       = ref('');
        const results     = ref([]);
        const selectedFile = ref(null);
        const useStream   = ref(true);
        const streamSrc   = ref('');
        const videoSrc    = ref('');
        const streamError = ref('');

        const canSearch = computed(() => startTime.value && endTime.value);

        // 格式化 datetime-local → NVR 格式 "YYYY-MM-DD HH:MM:SS"
        const toNvrTime = (dt) => dt.replace('T', ' ') + ':00';

        const search = async () => {
            if (!canSearch.value) return;
            loading.value  = true;
            error.value    = '';
            results.value  = [];
            selectedFile.value = null;

            try {
                const begin = toNvrTime(startTime.value);
                const end   = toNvrTime(endTime.value);
                const params = new URLSearchParams({
                    channels:   channel.value,
                    begin_time: begin,
                    end_time:   end,
                });
                const res  = await fetch(`/api/nvr/history?${params}`);
                const data = await res.json();

                if (!data.success) {
                    error.value = data.error || '查詢失敗';
                    return;
                }

                results.value = (data.data || []).flatMap(ch =>
                    (ch.FileList || []).map(f => ({
                        Tag:       f.Tag,
                        BeginTime: f.BeginTime,
                        EndTime:   f.EndTime,
                        Channel:   ch.Ch,
                        FileName:  f.FileName,
                    }))
                );

                if (results.value.length === 0) {
                    error.value = '該時段無錄影資料';
                }
            } catch (e) {
                error.value = '查詢錯誤：' + e.message;
            } finally {
                loading.value = false;
            }
        };

        const selectFile = (f) => {
            selectedFile.value = f;
            streamError.value  = '';
            useStream.value    = true;
            streamSrc.value    = `/api/nvr/playback_stream/${f.Channel}?time=${encodeURIComponent(f.BeginTime)}`;
            videoSrc.value     = `/api/nvr/download/avi?tag=${encodeURIComponent(f.Tag)}`;
        };

        const toggleMode = () => {
            useStream.value = !useStream.value;
            streamError.value = '';
        };

        const onStreamError = () => {
            streamError.value = 'NVR 串流連線失敗，請改用下載模式';
        };

        const downloadAvi = (tag) => window.open(`/api/nvr/download/avi?tag=${encodeURIComponent(tag)}`, '_blank');
        const downloadRaw = (tag) => window.open(`/api/nvr/download/raw?tag=${encodeURIComponent(tag)}`, '_blank');

        return {
            startTime, endTime, channel, loading, error, results,
            selectedFile, useStream, streamSrc, videoSrc, streamError,
            canSearch, search, selectFile, toggleMode, onStreamError,
            downloadAvi, downloadRaw,
        };
    }
};
