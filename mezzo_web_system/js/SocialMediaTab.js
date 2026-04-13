// js/SocialMediaTab.js
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { store, BASE } from './store.js';

export default {
    template: `
    <div class="w-full h-full overflow-y-auto bg-[#0f1115] p-6 space-y-6">

        <!-- Header -->
        <div class="flex justify-between items-center border-b border-gray-800 pb-4">
            <div>
                <h2 class="text-2xl font-bold text-gray-100">📲 Social Media</h2>
                <p class="text-xs text-gray-500 mt-1">WhatsApp Auto-Notification · STT Voice Recognition · Live Video Link Sharing</p>
            </div>
            <div class="flex items-center gap-3">
                <div class="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border"
                     :class="sttAvailable ? 'bg-green-900/30 border-green-700 text-green-400' : 'bg-gray-800 border-gray-700 text-gray-500'">
                    <span class="w-2 h-2 rounded-full" :class="sttAvailable ? 'bg-green-400 animate-pulse' : 'bg-gray-600'"></span>
                    STT {{ sttAvailable ? 'Enabled' : 'Disabled' }}
                </div>
                <div class="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full border"
                     :class="config.is_enabled ? 'bg-blue-900/30 border-blue-700 text-blue-400' : 'bg-gray-800 border-gray-700 text-gray-500'">
                    <span class="w-2 h-2 rounded-full" :class="config.is_enabled ? 'bg-blue-400 animate-pulse' : 'bg-gray-600'"></span>
                    WhatsApp {{ config.is_enabled ? 'Notification On' : 'Notification Off' }}
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">

            <!-- ── WhatsApp API Settings ── -->
            <div class="bg-gray-800 rounded-xl border border-gray-700 p-6 shadow-lg">
                <h3 class="text-lg font-bold text-green-400 mb-4 border-b border-gray-700 pb-2 flex items-center gap-2">
                    <span>💬</span> WhatsApp API Settings
                </h3>

                <div class="space-y-4">
                    <div>
                        <label class="text-xs text-gray-400 mb-1 block">API Provider</label>
                        <select v-model="config.provider"
                                class="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white outline-none focus:border-green-500">
                            <option value="meta">Meta (WhatsApp Cloud API)</option>
                            <option value="twilio">Twilio</option>
                        </select>
                    </div>

                    <div>
                        <label class="text-xs text-gray-400 mb-1 block">
                            {{ config.provider === 'meta' ? 'Access Token (Graph API)' : 'Auth Token' }}
                        </label>
                        <input v-model="config.access_token" type="password"
                               placeholder="Paste API Token"
                               class="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white outline-none focus:border-green-500 font-mono text-xs">
                    </div>

                    <div>
                        <label class="text-xs text-gray-400 mb-1 block">
                            {{ config.provider === 'meta' ? 'Phone Number ID' : 'Sender Number (with country code)' }}
                        </label>
                        <input v-model="config.phone_number_id" type="text"
                               :placeholder="config.provider === 'meta' ? '1234567890' : '886912345678'"
                               class="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white outline-none focus:border-green-500 font-mono">
                    </div>

                    <div v-if="config.provider === 'twilio'">
                        <label class="text-xs text-gray-400 mb-1 block">Account SID</label>
                        <input v-model="config.account_sid" type="text" placeholder="ACxxxxxxxx"
                               class="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white outline-none focus:border-green-500 font-mono text-xs">
                    </div>

                    <div>
                        <label class="text-xs text-gray-400 mb-1 block">Public Server URL</label>
                        <input v-model="config.public_url" type="text"
                               placeholder="http://your-server-ip"
                               class="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white outline-none focus:border-green-500 font-mono text-sm">
                    </div>

                    <div>
                        <label class="text-xs text-gray-400 mb-1 block">STT Trigger Keyword</label>
                        <input v-model="config.stt_keyword" type="text" placeholder="send video"
                               class="w-full bg-gray-900 border border-gray-600 rounded p-2 text-white outline-none focus:border-green-500">
                    </div>

                    <div class="flex items-center justify-between py-2 bg-gray-900 rounded-lg px-3 border border-gray-700">
                        <span class="text-sm text-gray-300 font-bold">Enable Auto WhatsApp Notification</span>
                        <button @click="config.is_enabled = !config.is_enabled"
                                :class="config.is_enabled ? 'bg-green-600' : 'bg-gray-700'"
                                class="w-12 h-6 rounded-full transition-colors relative">
                            <span :class="config.is_enabled ? 'translate-x-6' : 'translate-x-1'"
                                  class="absolute top-1 left-0 w-4 h-4 bg-white rounded-full transition-transform shadow"></span>
                        </button>
                    </div>

                    <div class="flex gap-3 pt-2">
                        <button @click="saveConfig"
                                class="flex-1 bg-green-700 hover:bg-green-600 text-white py-2 rounded font-bold transition-colors">
                            💾 Save Settings
                        </button>
                        <button @click="showTestPanel = !showTestPanel"
                                class="flex-1 bg-blue-800 hover:bg-blue-700 text-white py-2 rounded font-bold transition-colors">
                            🧪 Test Send
                        </button>
                    </div>

                    <div v-if="showTestPanel" class="bg-gray-900 rounded-lg border border-blue-700/50 p-4 space-y-3">
                        <p class="text-xs font-bold text-blue-400">Test Send WhatsApp Message</p>
                        <input v-model="testPhone" type="text" placeholder="886912345678"
                               class="w-full bg-gray-800 border border-gray-600 rounded p-2 text-white outline-none focus:border-blue-500 font-mono text-sm">
                        <button @click="sendTest" :disabled="testSending"
                                class="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 text-white py-2 rounded font-bold transition-colors">
                            {{ testSending ? 'Sending...' : 'Send Test Message' }}
                        </button>
                        <div v-if="testResult" class="text-xs rounded p-2 font-mono"
                             :class="testResult.success ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'">
                            {{ testResult.success ? '✅ Send successful' : '❌ Send failed' }}: {{ testResult.detail }}
                        </div>
                    </div>
                </div>
            </div>

            <!-- ── STT Monitoring & Live Records ── -->
            <div class="bg-gray-800 rounded-xl border border-gray-700 p-6 shadow-lg flex flex-col">
                <div class="flex justify-between items-center mb-4 border-b border-gray-700 pb-2">
                    <h3 class="text-lg font-bold text-purple-400 flex items-center gap-2">
                        <span>🎙️</span> STT Recognition Monitor
                    </h3>
                    <button @click="fetchLogs" class="text-gray-500 hover:text-purple-400 text-lg transition-colors">↻</button>
                </div>

                <div v-if="!sttAvailable" class="bg-yellow-900/20 border border-yellow-700/50 rounded-lg p-4 mb-4 text-xs text-yellow-400">
                    ⚠️ STT module not enabled. Please confirm <code class="bg-gray-900 px-1 rounded">faster-whisper</code> is installed.
                </div>

                <div class="grid grid-cols-3 gap-3 mb-4">
                    <div class="bg-gray-900 rounded-lg p-3 text-center border border-gray-700">
                        <div class="text-2xl font-bold text-purple-400">{{ totalLogs }}</div>
                        <div class="text-[10px] text-gray-500 mt-1">Total Recognitions</div>
                    </div>
                    <div class="bg-gray-900 rounded-lg p-3 text-center border border-gray-700">
                        <div class="text-2xl font-bold text-green-400">{{ keywordHits }}</div>
                        <div class="text-[10px] text-gray-500 mt-1">Keyword Triggers</div>
                    </div>
                    <div class="bg-gray-900 rounded-lg p-3 text-center border border-gray-700">
                        <div class="text-2xl font-bold text-blue-400">{{ sentCount }}</div>
                        <div class="text-[10px] text-gray-500 mt-1">WhatsApp Sent</div>
                    </div>
                </div>

                <div class="flex-1 overflow-y-auto space-y-2 max-h-[400px]">
                    <div v-if="logs.length === 0" class="text-xs text-center text-gray-600 py-8">
                        No STT recognition records yet
                    </div>
                    <div v-for="log in logs" :key="log.id"
                         class="p-3 rounded-lg border text-xs"
                         :class="log.keyword_detected ? 'bg-green-900/20 border-green-700/50' : 'bg-gray-900 border-gray-700'">
                        <div class="flex justify-between items-start mb-1">
                            <div class="flex items-center gap-2">
                                <span class="font-mono text-gray-500">{{ log.timestamp }}</span>
                                <span class="text-gray-400 font-mono">{{ log.device_id }}</span>
                            </div>
                            <span v-if="log.keyword_detected"
                                  class="px-1.5 py-0.5 bg-green-900/60 text-green-400 border border-green-700/50 rounded text-[10px] font-bold">
                                🎯 Keyword
                            </span>
                        </div>
                        <div class="text-gray-300 leading-relaxed mt-1">{{ log.transcript || '(No transcript)' }}</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ── User WhatsApp Number Management ── -->
        <div class="bg-gray-800 rounded-xl border border-gray-700 p-6 shadow-lg">
            <h3 class="text-lg font-bold text-blue-400 mb-4 border-b border-gray-700 pb-2">
                📱 User WhatsApp Notification List
            </h3>
            <div class="overflow-x-auto">
                <table class="w-full text-sm text-gray-300 text-left">
                    <thead class="bg-gray-900 text-gray-400">
                        <tr>
                            <th class="p-3">Username</th>
                            <th class="p-3">Role</th>
                            <th class="p-3">WhatsApp Number</th>
                            <th class="p-3">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="u in users" :key="u.username" class="border-t border-gray-700">
                            <td class="p-3 font-bold">{{ u.username }}</td>
                            <td class="p-3">
                                <span class="text-[10px] px-2 py-0.5 rounded font-bold"
                                      :class="u.role === 'admin' ? 'bg-red-900/30 text-red-400' : 'bg-gray-700 text-gray-400'">
                                    {{ u.role }}
                                </span>
                            </td>
                            <td class="p-3">
                                <input v-model="u.whatsapp_input" type="text"
                                       placeholder="886912345678"
                                       class="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-white outline-none focus:border-blue-500 font-mono text-xs w-52">
                            </td>
                            <td class="p-3">
                                <div class="flex items-center gap-2">
                                    <button @click="updateWhatsApp(u)"
                                            class="bg-blue-700 hover:bg-blue-600 text-white px-3 py-1 rounded text-xs font-bold">
                                        Save
                                    </button>
                                    <span v-if="u.save_ok" class="text-green-400 text-xs">✓</span>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    `,
    setup() {
        const config      = ref({
            provider: 'meta', access_token: '', phone_number_id: '',
            account_sid: '', public_url: '',
            stt_keyword: 'send video', is_enabled: false
        });
        const logs         = ref([]);
        const users        = ref([]);
        const sttAvailable = ref(false);
        const showTestPanel = ref(false);
        const testPhone    = ref('');
        const testSending  = ref(false);
        const testResult   = ref(null);
        let pollTimer = null;

        const totalLogs   = computed(() => logs.value.length);
        const keywordHits = computed(() => logs.value.filter(l => l.keyword_detected).length);
        const sentCount   = computed(() => logs.value.filter(l => l.status === 'sent' || l.status === 'partial').length);

        const fetchConfig = async () => {
            try {
                const res  = await fetch(`${BASE}/api/social/config`);
                const data = await res.json();
                if (Object.keys(data).length) Object.assign(config.value, data);
            } catch {}
        };

        const fetchLogs = async () => {
            try {
                const res = await fetch(`${BASE}/api/social/logs?limit=50`);
                logs.value = await res.json();
            } catch {}
        };

        const fetchUsers = async () => {
            try {
                const res  = await fetch(`${BASE}/api/users`);
                const data = await res.json();
                users.value = data.map(u => ({ ...u, whatsapp_input: u.whatsapp || '', save_ok: false }));
            } catch {}
        };

        const fetchSttStatus = async () => {
            try {
                const res  = await fetch(`${BASE}/api/social/stt_status`);
                const data = await res.json();
                sttAvailable.value = data.available;
            } catch {}
        };

        const saveConfig = async () => {
            await fetch(`${BASE}/api/social/config`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config.value)
            });
            alert('✅ Settings saved');
        };

        const sendTest = async () => {
            testSending.value = true;
            testResult.value  = null;
            try {
                const res  = await fetch(`${BASE}/api/social/test`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone: testPhone.value })
                });
                testResult.value = await res.json();
            } catch (e) {
                testResult.value = { success: false, detail: e.message };
            }
            testSending.value = false;
        };

        const updateWhatsApp = async (u) => {
            u.save_ok = false;
            const res = await fetch(`${BASE}/api/users/${u.username}/whatsapp`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ whatsapp: u.whatsapp_input })
            });
            if (res.ok) {
                u.whatsapp = u.whatsapp_input;
                u.save_ok  = true;
                setTimeout(() => { u.save_ok = false; }, 2000);
            }
        };

        onMounted(() => {
            fetchConfig(); fetchLogs(); fetchUsers(); fetchSttStatus();
            pollTimer = setInterval(fetchLogs, 10000);
        });
        onUnmounted(() => { if (pollTimer) clearInterval(pollTimer); });

        return {
            store, config, logs, users, sttAvailable,
            showTestPanel, testPhone, testSending, testResult,
            totalLogs, keywordHits, sentCount,
            fetchLogs, saveConfig, sendTest, updateWhatsApp
        };
    }
};
