// js/AdminTab.js
import { ref, onMounted } from 'vue';
import { store, BASE } from './store.js';

export default {
    template: `
        <div class="w-full h-full p-8 overflow-y-auto bg-[#0f1115]">
            <h2 class="text-2xl font-bold mb-6 text-gray-100 border-b border-gray-800 pb-2">
                {{ store.currentUser.role === 'admin' ? '系統後台管理 (Admin)' : '個人設定與設備綁定' }}
            </h2>
            
            <div class="grid grid-cols-1 xl:grid-cols-2 gap-8">
                
                <div class="bg-gray-800 rounded-xl border border-gray-700 p-6 shadow-lg">
                    <h3 class="text-lg font-bold mb-4 text-green-400 border-b border-gray-700 pb-2">綁定您的個人設備</h3>
                    <form @submit.prevent="bindDevice" class="flex gap-2 mb-6">
                        <input v-model="bindDevId" type="text" placeholder="輸入 Device ID 進行綁定" required class="flex-1 bg-gray-900 border border-gray-700 rounded p-2 text-white outline-none focus:border-green-500 transition-colors">
                        <button type="submit" class="bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded font-bold transition-colors">綁定設備</button>
                    </form>
                    
                    <h4 class="text-sm text-gray-400 mb-2">我管理的設備清單 ({{ store.devices.length }})</h4>
                    <div class="max-h-64 overflow-y-auto">
                        <table class="w-full text-left text-sm text-gray-300">
                            <thead class="bg-gray-900 text-gray-400"><tr><th class="p-2">設備名稱</th><th class="text-right p-2">操作</th></tr></thead>
                            <tbody>
                                <tr v-for="dev in store.devices" :key="dev.device_id" class="border-t border-gray-700 hover:bg-gray-750 transition-colors">
                                    <td class="p-2 font-bold">{{ dev.name }} <span class="text-xs text-gray-500 block font-mono">{{ dev.device_id }}</span></td>
                                    <td class="text-right p-2"><button @click="unbindDevice(dev.device_id)" class="text-orange-400 border border-orange-800 px-2 py-1 rounded text-xs hover:bg-orange-900/50 transition-colors">解綁</button></td>
                                </tr>
                                <tr v-if="store.devices.length === 0"><td colspan="2" class="p-4 text-center text-gray-500">尚未綁定任何設備</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <div v-if="store.currentUser.role === 'admin'" class="bg-gray-800 rounded-xl border border-gray-700 p-6 shadow-lg">
                    <h3 class="text-lg font-bold mb-4 text-purple-400 border-b border-gray-700 pb-2">系統設備總庫註冊</h3>
                    <form @submit.prevent="addDevice" class="space-y-4 mb-6">
                        <input v-model="newDev.device_id" type="text" placeholder="DeviceID (需與密錄器一致)" required class="w-full bg-gray-900 border border-gray-700 rounded p-2 text-white outline-none focus:border-purple-500 transition-colors">
                        <input v-model="newDev.name" type="text" placeholder="設備顯示名稱" required class="w-full bg-gray-900 border border-gray-700 rounded p-2 text-white outline-none focus:border-purple-500 transition-colors">
                        <button type="submit" class="w-full bg-purple-600 hover:bg-purple-500 text-white py-2 rounded font-bold transition-colors">新增設備入庫</button>
                    </form>
                    <table class="w-full text-left text-sm text-gray-300">
                        <thead class="bg-gray-900 text-gray-400"><tr><th class="p-2">系統內所有設備</th><th class="text-right p-2">操作</th></tr></thead>
                        <tbody>
                            <tr v-for="dev in allSysDevices" :key="dev.device_id" class="border-t border-gray-700 hover:bg-gray-750 transition-colors">
                                <td class="p-2 font-bold">{{ dev.name }} <span class="text-xs text-gray-500 block font-mono">{{ dev.device_id }}</span></td>
                                <td class="text-right p-2"><button @click="deleteDevice(dev.device_id)" class="text-red-400 border border-red-800 px-2 py-1 rounded text-xs hover:bg-red-900/50 transition-colors">徹底刪除</button></td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <div v-if="store.currentUser.role === 'admin'" class="bg-gray-800 rounded-xl border border-gray-700 p-6 xl:col-span-2 shadow-lg">
                    <h3 class="text-lg font-bold mb-4 text-purple-400 border-b border-gray-700 pb-2">使用者與群組階層管理</h3>
                    <div class="overflow-x-auto">
                        <table class="w-full text-left text-sm text-gray-300">
                            <thead class="bg-gray-900 text-gray-400">
                                <tr><th class="p-3">帳號 / Email</th><th class="p-3">目前權限角色</th><th class="p-3">所屬群組管理者</th><th class="p-3">密碼重設</th></tr>
                            </thead>
                            <tbody>
                                <tr v-for="user in users" :key="user.username" class="border-t border-gray-700 hover:bg-gray-750 transition-colors">
                                    <td class="p-3 font-bold">{{ user.username }} <span class="text-xs text-gray-500 block">{{ user.email || '未提供' }}</span></td>
                                    <td class="p-3">
                                        <select v-model="user.role" @change="updateUserGroup(user)" class="bg-gray-900 border border-gray-600 rounded p-1 text-xs outline-none text-white focus:border-purple-500">
                                            <option value="operator">一般調度員</option>
                                            <option value="group_manager">群組管理者 (可看下屬)</option>
                                            <option value="admin">系統管理員</option>
                                        </select>
                                    </td>
                                    <td class="p-3">
                                        <select v-if="user.role === 'operator'" v-model="user.manager" @change="updateUserGroup(user)" class="bg-gray-900 border border-gray-600 rounded p-1 text-xs outline-none text-purple-300 focus:border-purple-500">
                                            <option :value="null">無所屬群組</option>
                                            <option v-for="mgr in managers" :key="mgr.username" :value="mgr.username">{{ mgr.username }}</option>
                                        </select>
                                        <span v-else class="text-gray-500 text-xs">無需指派</span>
                                    </td>
                                    <td class="p-3">
                                        <button @click="resetPwd(user.username)" class="bg-gray-700 hover:bg-gray-600 text-white px-2 py-1 rounded text-xs border border-gray-600 transition-colors">重設密碼</button>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

            </div>
        </div>
    `,
    setup() {
        const users = ref([]);
        const allSysDevices = ref([]);
        const newDev = ref({ device_id: '', name: '' });
        const bindDevId = ref('');

        // 過濾出所有可以被當作「群組管理者」的帳號
        const managers = ref([]);

        const fetchData = async () => {
            if(store.currentUser.role === 'admin') {
                const devRes = await fetch(`${BASE}/api/admin/all_devices`);
                allSysDevices.value = await devRes.json();
                
                const userRes = await fetch(`${BASE}/api/users`);
                users.value = await userRes.json();
                managers.value = users.value.filter(u => u.role === 'group_manager' || u.role === 'admin');
            }
        };

        const addDevice = async () => {
            const res = await fetch(`${BASE}/api/devices`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(newDev.value) });
            if(res.ok) { newDev.value = { device_id: '', name: '' }; fetchData(); }
            else { alert(await res.text()); }
        };

        const deleteDevice = async (id) => {
            if(confirm('確定從系統徹底刪除?')) { await fetch(`${BASE}/api/devices/${id}`, { method: 'DELETE' }); fetchData(); store.fetchDevices(); }
        };

        const bindDevice = async () => {
            const res = await fetch(`${BASE}/api/users/${store.currentUser.username}/bind`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({device_id: bindDevId.value}) });
            if(res.ok) { bindDevId.value = ''; store.fetchDevices(); }
            else { alert("綁定失敗，請確認 Device ID 是否註冊於系統中"); }
        };

        const unbindDevice = async (id) => {
            if(confirm('解除綁定後將無法監看此設備?')) { await fetch(`${BASE}/api/users/${store.currentUser.username}/unbind/${id}`, { method: 'DELETE' }); store.fetchDevices(); }
        };

        const updateUserGroup = async (user) => {
            await fetch(`${BASE}/api/users/${user.username}/assign_manager`, { 
                method: 'PUT', headers: {'Content-Type': 'application/json'}, 
                body: JSON.stringify({ role: user.role, manager_username: user.manager }) 
            });
            fetchData(); 
        };

        const resetPwd = async (username) => {
            const newPwd = prompt(`請輸入 ${username} 的新密碼:`);
            if(newPwd) {
                await fetch(`${BASE}/api/users/${username}/reset_password`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({new_password: newPwd}) });
                alert("密碼已重設");
            }
        };

        onMounted(() => { fetchData(); });
        return { store, users, managers, allSysDevices, newDev, bindDevId, addDevice, deleteDevice, bindDevice, unbindDevice, updateUserGroup, resetPwd };
    }
};