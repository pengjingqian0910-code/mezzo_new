// js/PttTab.js
import { ref, onMounted, onUnmounted, nextTick } from 'vue';
import { store, BASE } from './store.js';

export default {
    template: `
        <div class="w-full h-full flex bg-[#0f1115]">
            <div class="w-80 bg-gray-800 border-r border-gray-700 flex flex-col z-10 shadow-xl">
                <div class="p-3 bg-gray-900 border-b border-gray-800 flex justify-between items-center text-xs">
                    <span class="text-gray-500 font-bold tracking-wider">COMMUNICATION LINK</span>
                    <span class="flex items-center gap-2" :class="isMqttConnected ? 'text-[#00f6ff]' : 'text-red-500'">
                        <span class="h-2 w-2 rounded-full" :class="isMqttConnected ? 'bg-[#00f6ff]' : 'bg-red-500'"></span>
                        {{ isMqttConnected ? 'ONLINE' : 'OFFLINE' }}
                    </span>
                </div>

                <div class="p-4 flex-1 overflow-y-auto">
                    <h3 class="text-sm font-bold text-gray-300 mb-3 flex items-center gap-2">
                        <span>🎯 戰術遠端監聽</span>
                    </h3>
                    
                    <div class="bg-gray-900 p-4 rounded-xl border mb-6 transition-all duration-300"
                         :class="isPrivateCalling ? 'border-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.2)]' : 'border-gray-700'">
                        <div class="flex justify-between items-center mb-3">
                            <span class="text-sm font-mono font-bold" :class="isPrivateCalling ? 'text-red-400' : 'text-gray-400'">
                                ID: {{ targetDevice || '請選擇設備' }}
                            </span>
                            <span v-if="isPrivateCalling" class="text-[10px] bg-red-900/50 text-red-400 px-2 py-0.5 rounded animate-pulse">監聽中</span>
                        </div>
                        
                        <button @click="toggleRemoteListen" 
                                :disabled="!isMqttConnected || !targetDevice"
                                :class="[
                                    (!isMqttConnected || !targetDevice) ? 'bg-gray-700 text-gray-500 cursor-not-allowed' : 
                                    isPrivateCalling ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-purple-600 hover:bg-purple-500 text-white'
                                ]" 
                                class="w-full py-2 rounded font-bold transition-colors flex items-center justify-center gap-2">
                            <span v-if="isPrivateCalling">⏹ 停止監聽</span>
                            <span v-else>🎧 啟動遠端監聽</span>
                        </button>
                    </div>

                    <h3 class="text-sm font-bold text-[#00f6ff] mb-1 border-b border-gray-700 pb-2 flex items-center gap-2">
                        <span class="animate-pulse h-2 w-2 bg-[#00f6ff] rounded-full"></span> 頻道上線設備 (SPEECH)
                    </h3>
                    <p class="text-[10px] text-gray-500 mb-3">點擊設備可將其設為遠端監聽目標</p>
                    
                    <div v-if="onlineDevices.length === 0" class="text-xs text-gray-500 mb-6 text-center bg-gray-900/50 py-4 rounded border border-gray-800">目前尚無設備封包紀錄</div>
                    <div v-else class="mb-6 space-y-2">
                        <div v-for="devId in onlineDevices" :key="devId" 
                             @click="targetDevice = devId"
                             :class="targetDevice === devId ? 'border-purple-500 bg-gray-800' : 'border-gray-700 bg-gray-900 hover:border-gray-500'"
                             class="p-2 border rounded flex justify-between items-center cursor-pointer transition-colors shadow-sm">
                            <span class="text-xs font-mono" :class="targetDevice === devId ? 'text-purple-400 font-bold' : 'text-gray-300'">{{ devId }}</span>
                            <span v-if="activeGroupSpeaker === devId" class="text-[9px] bg-[#00f6ff]/20 text-[#00f6ff] border border-[#00f6ff]/30 px-1.5 py-0.5 rounded animate-pulse">發話中</span>
                            <span v-else class="text-[9px] text-gray-500">在線</span>
                        </div>
                    </div>

                    <h3 class="text-sm font-bold text-gray-300 mb-3 border-b border-gray-700 pb-2">📡 一般廣播群組</h3>
                    <div v-for="i in 5" :key="i" @click="activeGroup = i" 
                         :class="activeGroup === i ? 'bg-blue-900 border-blue-500' : 'bg-gray-900 border-gray-700 hover:border-blue-400'" 
                         class="mb-2 p-3 rounded border cursor-pointer flex justify-between items-center transition-colors">
                        <span class="text-sm font-bold text-gray-200">CHANNEL{{ String(i).padStart(4, '0') }}</span>
                    </div>
                </div>
            </div>

            <div class="flex-1 flex flex-col items-center justify-center relative border-r border-gray-800 bg-[#0f1115]">
                
                <div v-if="isPrivateCalling" class="absolute top-10 flex flex-col items-center bg-red-900/30 border border-red-500/50 p-6 rounded-2xl shadow-[0_0_30px_rgba(239,68,68,0.2)] z-10 backdrop-blur-md">
                    <span class="text-red-400 font-bold mb-2 animate-pulse">⚠️ 收到私人語音通話 (Private Call)</span>
                    <span class="text-white text-lg font-mono mb-1">來源設備: {{ targetDevice }}</span>
                    <span class="text-xs text-gray-400 font-mono">交握 Topic: {{ currentPrivateTopic }}</span>
                    <div class="mt-4 flex items-center gap-3">
                        <div class="flex gap-1">
                            <div class="w-1.5 h-4 bg-[#00f6ff] rounded-full animate-[bounce_1s_infinite]"></div>
                            <div class="w-1.5 h-6 bg-[#00f6ff] rounded-full animate-[bounce_1s_infinite_0.2s]"></div>
                            <div class="w-1.5 h-3 bg-[#00f6ff] rounded-full animate-[bounce_1s_infinite_0.4s]"></div>
                            <div class="w-1.5 h-5 bg-[#00f6ff] rounded-full animate-[bounce_1s_infinite_0.1s]"></div>
                        </div>
                        <span class="text-xs text-[#00f6ff] font-bold tracking-widest">AUDIO STREAMING...</span>
                    </div>
                </div>

                <div v-else-if="activeGroupSpeaker" class="absolute top-10 flex flex-col items-center bg-blue-900/30 border border-blue-500/50 p-4 rounded-xl shadow-[0_0_20px_rgba(59,130,246,0.2)] z-10 backdrop-blur-sm">
                    <span class="text-blue-400 font-bold mb-1 text-sm">📡 接收頻道廣播中...</span>
                    <span class="text-white font-mono text-lg">{{ activeGroupSpeaker }}</span>
                </div>

                <div class="absolute top-8 right-8 flex items-center gap-3 bg-gray-900 px-4 py-2 rounded-full border border-gray-700">
                    <span class="text-xs font-bold" :class="sttEnabled ? 'text-blue-400' : 'text-gray-500'">本機 AI STT (發話用)</span>
                    <button @click="sttEnabled = !sttEnabled" :class="sttEnabled ? 'bg-blue-600' : 'bg-gray-600'" class="w-10 h-5 rounded-full relative transition-colors duration-300">
                        <div :class="sttEnabled ? 'translate-x-5' : 'translate-x-0'" class="w-5 h-5 bg-white rounded-full shadow transform transition-transform duration-300"></div>
                    </button>
                </div>

                <div @mousedown="startTalking" @mouseup="stopTalking" @mouseleave="stopTalking" 
                     :class="[
                        isTalking ? 'bg-[#00aaaa] border-[#00f6ff] scale-110 shadow-[0_0_80px_rgba(0,246,255,0.6)]' : 'bg-gray-800 border-gray-600 hover:border-blue-500',
                        (isPrivateCalling || activeGroupSpeaker) ? 'opacity-30 pointer-events-none grayscale' : ''
                     ]" 
                     class="w-72 h-72 rounded-full border-4 flex flex-col items-center justify-center cursor-pointer transition-all duration-200 select-none">
                    <div class="text-6xl mb-4">🎙️</div>
                    <div class="text-xl font-bold text-white mb-2">群組 {{ activeGroup }}</div>
                    <div class="text-sm font-bold text-center px-4" :class="isTalking ? 'text-white' : 'text-gray-400'">
                        <span v-if="isTalking">發話錄音中...</span>
                        <span v-else-if="isPrivateCalling">遠端監聽中 (鎖定本機麥克風)</span>
                        <span v-else-if="activeGroupSpeaker">頻道被占用 (鎖定本機麥克風)</span>
                        <span v-else>按住滑鼠發話 (PTT)</span>
                    </div>
                </div>
            </div>

            <div class="w-[450px] bg-gray-900 flex flex-col">
                <div class="flex border-b border-gray-700 bg-gray-800">
                    <button @click="panelTab = 'live'" :class="panelTab === 'live' ? 'text-blue-400 border-b-2 border-blue-500 bg-gray-900' : 'text-gray-400 hover:text-white'" class="flex-1 py-3 text-sm font-bold transition-colors">即時通訊 (Live)</button>
                    <button @click="panelTab = 'history'" :class="panelTab === 'history' ? 'text-blue-400 border-b-2 border-blue-500 bg-gray-900' : 'text-gray-400 hover:text-white'" class="flex-1 py-3 text-sm font-bold transition-colors">語音檔案查詢</button>
                </div>
                
                <div v-show="panelTab === 'live'" class="flex-1 overflow-y-auto p-4 space-y-3" id="liveBox">
                    <div v-for="(msg, index) in liveLog" :key="index" class="bg-gray-800 p-3 rounded-lg border border-gray-700 relative overflow-hidden">
                        <div v-if="msg.isPrivate" class="absolute top-0 left-0 w-1 h-full bg-red-500"></div>
                        <div v-else-if="msg.isBroadcast" class="absolute top-0 left-0 w-1 h-full bg-[#00f6ff]"></div>
                        <div v-else class="absolute top-0 left-0 w-1 h-full bg-blue-500"></div>
                        
                        <div class="flex justify-between text-[10px] text-gray-400 mb-1 pl-2">
                            <span class="font-bold" :class="msg.isPrivate ? 'text-red-400' : (msg.isBroadcast ? 'text-[#00f6ff]' : 'text-blue-300')">
                                {{ msg.sender }} 
                                <span v-if="msg.isPrivate" class="bg-red-900/50 px-1 rounded text-[8px] ml-1">Private Call</span>
                                <span v-if="msg.isBroadcast" class="bg-[#00f6ff]/20 border border-[#00f6ff]/30 px-1 rounded text-[8px] ml-1 text-[#00f6ff]">Group Speech</span>
                            </span>
                            <span>{{ msg.time }}</span>
                        </div>
                        <div class="text-sm text-gray-100 pl-2 leading-relaxed">{{ msg.text }}</div>
                        <audio v-if="msg.audio_url" :src="msg.audio_url" controls class="w-full h-8 mt-2 opacity-80 outline-none"></audio>
                    </div>

                    <div v-if="(isTalking || isPrivateCalling || activeGroupSpeaker) && interimText" class="bg-blue-900/30 p-3 rounded-lg border border-blue-500/50 pl-3">
                        <div class="text-[10px] text-blue-400 font-bold mb-1">AI STT 辨識中...</div>
                        <div class="text-sm text-gray-100 animate-pulse">{{ interimText }}</div>
                    </div>
                </div>

                <div v-show="panelTab === 'history'" class="flex-1 overflow-y-auto p-4 bg-[#0f1115]">
                    <div class="flex gap-2 mb-4">
                        <input v-model="searchQuery" type="text" placeholder="輸入 Device ID 搜尋" class="flex-1 bg-gray-800 border border-gray-700 rounded px-2 text-xs text-white outline-none">
                        <button @click="fetchHistory" class="bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 py-1 rounded">查詢</button>
                    </div>

                    <div v-if="historyRecords.length === 0" class="text-center text-gray-500 text-sm mt-10">尚無歷史語音紀錄</div>

                    <div v-for="rec in historyRecords" :key="rec.id" class="bg-gray-800 p-3 rounded-lg border border-gray-700 mb-3 relative overflow-hidden">
                        <div :class="rec.sender === targetDevice ? 'bg-red-500' : 'bg-blue-500'" class="absolute top-0 left-0 w-1 h-full"></div>
                        <div class="flex justify-between text-[10px] text-gray-400 mb-2 border-b border-gray-700 pb-1 pl-2">
                            <span class="font-bold" :class="rec.sender === targetDevice ? 'text-red-400' : 'text-[#00f6ff]'">{{ rec.sender }}</span>
                            <span>{{ rec.timestamp }}</span>
                        </div>
                        <div class="text-sm text-gray-100 mb-2 pl-2 leading-relaxed">{{ rec.text || '（無辨識文字）' }}</div>
                        <audio :src="rec.audio_url" controls class="w-full h-8 outline-none ml-2 w-[calc(100%-8px)]"></audio>
                    </div>
                </div>
            </div>
        </div>
    `,
    setup() {
        const channelPrefix = '/WJI/PTT/CHANNEL0001';
        let wsClient = null;
        const isMqttConnected = ref(false);

        const activeGroup = ref(1);
        const panelTab = ref('live'); 
        const searchQuery = ref('');
        
        // ================= 動態線上設備清單 =================
        // 初始化為空，透過後端 MQTT TCP 代理動態取得
        const onlineDevices = ref([]); 
        const targetDevice = ref(''); 
        
        const activeGroupSpeaker = ref(null); 
        let groupSpeechTimeout = null;
        let groupAudioChunks = [];
        
        const isPrivateCalling = ref(false);
        const currentPrivateTopic = ref('');
        let audioContext = null;
        let incomingAudioChunks = []; 
        let mockSttInterval = null;

        const isTalking = ref(false);
        const sttEnabled = ref(true);
        const liveLog = ref([]);
        const interimText = ref('');
        const historyRecords = ref([]);

        let recognition = null;
        let mediaRecorder = null;
        let localAudioChunks = [];
        let finalTranscripts = '';

        // ================= 1. 透過 WebSocket 與後端 TCP MQTT 代理連線 =================
        const connectBackendProxy = () => {
            const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            wsClient = new WebSocket(`${wsProto}//${location.host}${BASE}/ws/ptt`);
            
            wsClient.onopen = () => {
                isMqttConnected.value = true;
                console.log("🟢 [Proxy] 成功與後端 MQTT 代理連線！");
            };

            wsClient.onmessage = (event) => {
                const data = JSON.parse(event.data);
                const topic = data.topic;
                
                // 將後端傳來的 Base64 解析回 Uint8Array 原始音訊 Bytes
                const binaryString = atob(data.payload);
                const len = binaryString.length;
                const bytes = new Uint8Array(len);
                for (let i = 0; i < len; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                
                handleMqttMessage(topic, bytes);
            };

            wsClient.onclose = () => {
                isMqttConnected.value = false;
                console.warn("⚠️ [Proxy] 與後端代理連線中斷，5秒後重試...");
                setTimeout(connectBackendProxy, 5000);
            };
        };

        // 供前端主動 Publish 使用
        const publishToMqtt = (topic, payloadStr) => {
            if (wsClient && wsClient.readyState === WebSocket.OPEN) {
                wsClient.send(JSON.stringify({ action: 'publish', topic: topic, payload: payloadStr }));
            }
        };

        const registerOnlineDevice = (deviceId) => {
            if (deviceId && !onlineDevices.value.includes(deviceId)) {
                onlineDevices.value.push(deviceId);
                console.log(`📌 [MQTT Debug] 發現新設備上線: ${deviceId}`);
                if (!targetDevice.value) targetDevice.value = deviceId;
            }
        };

        // ================= MQTT 訊息分配器 =================
        const handleMqttMessage = (topic, bytes) => {
            if (topic === `${channelPrefix}/SPEECH`) {
                handleGroupSpeech(bytes);
                return;
            }

            if (topic === `${channelPrefix}/CHANNEL_ANNOUNCE`) {
                let payload = "";
                try { payload = new TextDecoder().decode(bytes); } catch(e) {}
                
                const parts = payload.split(',');
                if (parts.length >= 2) {
                    const extractedId = parts[1].trim();
                    registerOnlineDevice(extractedId);
                    
                    if (payload.includes('PRIVATE_SPK_REQ') && extractedId === targetDevice.value) {
                        if (parts.length >= 3 && !isPrivateCalling.value) {
                            startPrivateCallReceive(parts[2].trim());
                        }
                    }
                    else if (payload.includes('PRIVATE_SPK_STOP') && extractedId === targetDevice.value) {
                        stopPrivateCallReceive();
                    }
                }
                return;
            }
            
            if (isPrivateCalling.value && topic === `${channelPrefix}/PRIVATE/${currentPrivateTopic.value}`) {
                playIncomingAudio(bytes);
                incomingAudioChunks.push(bytes); 
            }
        };

        // ================= 全域廣播頻道處理 (SPEECH) =================
        const handleGroupSpeech = (buffer) => {
            const extractedDeviceId = parseDeviceIdFromBuffer(buffer);
            registerOnlineDevice(extractedDeviceId);
            activeGroupSpeaker.value = extractedDeviceId;
            
            playIncomingAudio(buffer);
            groupAudioChunks.push(buffer);
            
            interimText.value = `[${extractedDeviceId}] 群組語音解析中...`;

            clearTimeout(groupSpeechTimeout);
            groupSpeechTimeout = setTimeout(() => {
                endGroupSpeech(extractedDeviceId);
            }, 1500);
        };

        const parseDeviceIdFromBuffer = (_buffer) => {
            // TODO: 依實際協議從 Uint8Array 提取 Device ID
            return '688FC9D99DDB';
        };

        const endGroupSpeech = async (deviceId) => {
            const finalMockText = `【頻道廣播】這是來自 ${deviceId} 在 CHANNEL0001 的語音訊息。`;
            const audioBlob = new Blob(groupAudioChunks, { type: 'application/octet-stream' });
            await uploadRecord(audioBlob, finalMockText, deviceId, false, true);
            groupAudioChunks = [];
            activeGroupSpeaker.value = null;
            interimText.value = '';
        };

        // ================= 遠端監聽核心邏輯 (私人通話) =================
        const toggleRemoteListen = () => {
            if (!isMqttConnected.value) return alert("系統與後端通訊尚未連線！");
            if (!targetDevice.value) return alert("請先從上方列表中選擇一個目標設備！");

            if (isPrivateCalling.value) {
                sendPrivateStop();
                stopPrivateCallReceive();
            } else {
                const randomRoomId = 'Room-' + Math.random().toString(36).substring(2, 8).toUpperCase();
                const payload = `PRIVATE_SPK_REQ,${targetDevice.value},${randomRoomId}`;
                publishToMqtt(`${channelPrefix}/CHANNEL_ANNOUNCE`, payload);
                startPrivateCallReceive(randomRoomId);
            }
        };

        const sendPrivateStop = () => {
            if (isMqttConnected.value && targetDevice.value) {
                const payload = `PRIVATE_SPK_STOP,${targetDevice.value}`;
                publishToMqtt(`${channelPrefix}/CHANNEL_ANNOUNCE`, payload);
            }
        };

        const startPrivateCallReceive = (topicId) => {
            isPrivateCalling.value = true;
            currentPrivateTopic.value = topicId;
            incomingAudioChunks = [];
            interimText.value = '';
            
            if (!audioContext) audioContext = new (window.AudioContext || window['webkitAudioContext'])();
            if (audioContext.state === 'suspended') audioContext.resume();

            let dotCount = 0;
            mockSttInterval = setInterval(() => {
                dotCount++;
                interimText.value = `[來自 ${targetDevice.value}] AI 遠端訊號解析轉譯中` + '.'.repeat(dotCount % 4);
            }, 500);
        };

        const stopPrivateCallReceive = async () => {
            if (!isPrivateCalling.value) return;
            isPrivateCalling.value = false;
            clearInterval(mockSttInterval);
            
            const finalMockText = `【設備回報】這是一段來自 ${targetDevice.value} 的遠端私人通話擷取紀錄。系統已將 Raw Data 進行轉譯存檔。`;
            interimText.value = '';

            const audioBlob = new Blob(incomingAudioChunks, { type: 'application/octet-stream' });
            await uploadRecord(audioBlob, finalMockText, targetDevice.value, true, false);
        };

        const playIncomingAudio = (buffer) => {
            if (!audioContext) audioContext = new (window.AudioContext || window['webkitAudioContext'])();
            if (audioContext.state === 'suspended') audioContext.resume();
            try {} catch (e) { }
        };

        // ================= 本機發話與上傳 =================
        const initLocalAudioSystem = async () => {
            if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition = new SpeechRecognition();
                recognition.continuous = true;      
                recognition.interimResults = true;  
                recognition.lang = 'zh-TW';         

                recognition.onresult = (event) => {
                    interimText.value = '';
                    for (let i = event.resultIndex; i < event.results.length; i++) {
                        if (event.results[i].isFinal) finalTranscripts += event.results[i][0].transcript;
                        else interimText.value += event.results[i][0].transcript;
                    }
                };
            }

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) localAudioChunks.push(e.data); };
                mediaRecorder.onstop = async () => {
                    const audioBlob = new Blob(localAudioChunks, { type: 'audio/webm' });
                    localAudioChunks = []; 
                    const textToSave = finalTranscripts || interimText.value || '（未說話）';
                    await uploadRecord(audioBlob, textToSave, store.currentUser ? store.currentUser.username : '調度中心', false, false);
                    finalTranscripts = ''; 
                    interimText.value = '';
                };
            } catch (err) {}
        };

        const startTalking = () => {
            if (isPrivateCalling.value || activeGroupSpeaker.value || !mediaRecorder) return;
            isTalking.value = true;
            finalTranscripts = ''; interimText.value = '';
            mediaRecorder.start();
            if (sttEnabled.value && recognition) { try { recognition.start(); } catch(e){} }
        };

        const stopTalking = () => {
            if (!isTalking.value) return; 
            isTalking.value = false;
            if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
            if (recognition) recognition.stop();
        };

        // 音訊不落地存 DB，只更新前端 liveLog（即時顯示）
        const uploadRecord = async (audioBlob, text, senderName, isPrivate, isBroadcast = false) => {
            liveLog.value.push({
                time: new Date().toLocaleTimeString('zh-TW', { hour12: false }),
                sender: senderName,
                text: text,
                audio_url: URL.createObjectURL(audioBlob),
                isPrivate: isPrivate,
                isBroadcast: isBroadcast
            });
            scrollToBottom();
        };

        // 歷史音檔從 /api/audio/{device_id} 取得（NVR 同機儲存端寫入）
        const fetchHistory = async () => {
            const deviceId = searchQuery.value || targetDevice.value;
            if (!deviceId) { historyRecords.value = []; return; }
            try {
                const res = await fetch(`${BASE}/api/audio/${encodeURIComponent(deviceId)}`);
                const files = await res.json();
                historyRecords.value = files.map(f => ({
                    id: f.filename,
                    sender: deviceId,
                    text: '',
                    audio_url: f.url,
                    timestamp: f.filename
                }));
            } catch (e) {
                console.error('fetchHistory error', e);
                historyRecords.value = [];
            }
        };

        const scrollToBottom = async () => { await nextTick(); const box = document.getElementById('liveBox'); if (box) box.scrollTop = box.scrollHeight; };

        onMounted(() => { connectBackendProxy(); initLocalAudioSystem(); fetchHistory(); });
        onUnmounted(() => { if (recognition) recognition.stop(); if (wsClient) wsClient.close(); if (audioContext) audioContext.close(); clearTimeout(groupSpeechTimeout); });

        return { 
            activeGroup, isTalking, sttEnabled, panelTab, searchQuery, liveLog, interimText, historyRecords,
            isMqttConnected, targetDevice, isPrivateCalling, currentPrivateTopic, onlineDevices, activeGroupSpeaker,
            startTalking, stopTalking, fetchHistory, toggleRemoteListen 
        };
    }
};