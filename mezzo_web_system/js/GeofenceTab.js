// js/GeofenceTab.js
import { ref, onMounted, onUnmounted } from 'vue';
import { store } from './store.js';

export default {
    template: `
        <div class="w-full h-full flex">
            <div class="w-80 bg-gray-800 border-r border-gray-700 p-6 flex flex-col z-10 shadow-xl">
                <h3 class="text-xl font-bold text-blue-400 border-b border-gray-700 pb-2 mb-4">警戒區設定</h3>
                
                <div class="bg-gray-900 p-4 rounded border border-gray-700 mb-6">
                    <p class="text-xs text-gray-400 mb-2">【操作說明】</p>
                    <ul class="text-xs text-gray-300 list-disc pl-4 space-y-1">
                        <li>點擊 <strong>「開始繪製」</strong>。</li>
                        <li>在地圖上 <strong>左鍵點擊</strong> 設定頂點。</li>
                        <li>點擊 <strong>右鍵</strong> 閉合區塊並儲存。</li>
                    </ul>
                    <button @click="startDrawing" :disabled="isDrawing" :class="isDrawing ? 'bg-gray-600' : 'bg-blue-600 hover:bg-blue-500'" class="w-full mt-4 text-white font-bold py-2 rounded">
                        {{ isDrawing ? '繪製中 (請在地圖點擊)' : '開始繪製新警戒區' }}
                    </button>
                </div>

                <div class="flex-1 overflow-y-auto">
                    <h4 class="text-sm font-bold text-gray-400 mb-3">已儲存警戒區 ({{ store.geofences.length }})</h4>
                    <div v-for="geo in store.geofences" :key="geo.id" class="mb-3 p-3 bg-gray-900 rounded border border-gray-700">
                        <div class="flex justify-between items-center mb-2">
                            <span class="font-bold text-sm text-white">{{ geo.name }}</span>
                            <button @click="toggleGeo(geo.id)" :class="geo.is_enabled ? 'bg-green-600' : 'bg-gray-600'" class="px-2 py-1 text-[10px] text-white rounded font-bold">
                                {{ geo.is_enabled ? '啟用中' : '已停用' }}
                            </button>
                        </div>
                        <div class="flex justify-end">
                            <button @click="deleteGeo(geo.id)" class="text-red-400 hover:text-white text-xs px-2 py-1 border border-red-800 rounded">刪除</button>
                        </div>
                    </div>
                </div>
            </div>

            <div class="flex-1 relative">
                <div id="drawContainer" class="w-full h-full"></div>
            </div>
        </div>
    `,
    setup() {
        let drawViewer = null;
        let handler = null;
        const isDrawing = ref(false);
        const tempPoints = ref([]);
        let tempEntity = null; // 繪製中的多邊形實體

        const initDrawMap = () => {
            drawViewer = new Cesium.Viewer('drawContainer', {
                baseLayerPicker: false, imageryProvider: false, 
                geocoder: false, homeButton: false, infoBox: false,
                navigationHelpButton: false, sceneModePicker: false, 
                timeline: false, animation: false
            });
            const baseMap = new Cesium.UrlTemplateImageryProvider({ url: 'https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}' });
            drawViewer.imageryLayers.addImageryProvider(baseMap);
            drawViewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(121.5644, 25.0330, 3000.0) });

            // 設定滑鼠點擊事件
            handler = new Cesium.ScreenSpaceEventHandler(drawViewer.scene.canvas);
            
            // 左鍵加入點位
            handler.setInputAction((click) => {
                if (!isDrawing.value) return;
                const cartesian = drawViewer.camera.pickEllipsoid(click.position, drawViewer.scene.globe.ellipsoid);
                if (cartesian) {
                    const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                    tempPoints.value.push({ lng: Cesium.Math.toDegrees(cartographic.longitude), lat: Cesium.Math.toDegrees(cartographic.latitude) });
                    renderTempPolygon();
                }
            }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

            // 右鍵完成繪製
            handler.setInputAction(async (click) => {
                if (!isDrawing.value || tempPoints.value.length < 3) return;
                isDrawing.value = false;
                
                const geoName = prompt("請輸入警戒區名稱：", "新管制區");
                if (geoName) {
                    await fetch('http://localhost:5555/api/geofences', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: geoName, points: JSON.stringify(tempPoints.value) })
                    });
                    store.fetchGeofences(); // 重新拉取並更新全域狀態
                }
                
                // 清除暫存
                tempPoints.value = [];
                if (tempEntity) drawViewer.entities.remove(tempEntity);
            }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
        };

        const renderTempPolygon = () => {
            if (tempEntity) drawViewer.entities.remove(tempEntity);
            const degreesArray = tempPoints.value.flatMap(p => [p.lng, p.lat]);
            
            tempEntity = drawViewer.entities.add({
                polygon: {
                    hierarchy: Cesium.Cartesian3.fromDegreesArray(degreesArray),
                    material: Cesium.Color.ORANGE.withAlpha(0.4),
                    outline: true, outlineColor: Cesium.Color.ORANGE
                }
            });
            // 畫出頂點
            tempPoints.value.forEach(p => {
                drawViewer.entities.add({ position: Cesium.Cartesian3.fromDegrees(p.lng, p.lat), point: { pixelSize: 10, color: Cesium.Color.RED } });
            });
        };

        const startDrawing = () => { isDrawing.value = true; tempPoints.value = []; };
        const toggleGeo = async (id) => {
            await fetch(`http://localhost:5555/api/geofences/${id}/toggle`, { method: 'PUT' });
            store.fetchGeofences();
        };
        const deleteGeo = async (id) => {
            if (confirm("確定刪除此警戒區？")) {
                await fetch(`http://localhost:5555/api/geofences/${id}`, { method: 'DELETE' });
                store.fetchGeofences();
            }
        };

        onMounted(() => { initDrawMap(); store.fetchGeofences(); });
        onUnmounted(() => { if (drawViewer) drawViewer.destroy(); });

        return { store, isDrawing, startDrawing, toggleGeo, deleteGeo };
    }
};