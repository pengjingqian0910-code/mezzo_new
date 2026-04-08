// js/MapTab.js
import { ref, onMounted, watch, onUnmounted } from 'vue';
import { store } from './store.js';

export default {
    template: `
        <div class="w-full h-full relative">
            <div id="cesiumContainer" class="w-full h-full"></div>
            
            <div v-if="store.alerts.length > 0" class="absolute top-4 right-4 bg-red-600/90 text-white px-6 py-3 rounded-lg shadow-[0_0_20px_rgba(220,38,38,0.8)] border border-red-400 animate-pulse z-20 flex items-center gap-3">
                <span class="text-2xl">⚠️</span>
                <div>
                    <div class="font-bold">警戒區入侵警報！</div>
                    <div class="text-sm">設備 ID: {{ store.alerts.join(', ') }} 已進入限制區域</div>
                </div>
            </div>
            
            <div class="absolute top-4 left-4 w-64 bg-gray-900/80 backdrop-blur border border-gray-700 rounded-lg p-4 shadow-lg z-10 max-h-[80vh] overflow-y-auto">
                <h3 class="text-sm font-bold text-gray-300 mb-3">線上設備定位</h3>
                <div v-for="dev in store.devices" :key="dev.device_id" @click="focusDevice(dev)" 
                     class="mb-2 p-2 rounded border cursor-pointer transition-colors"
                     :class="store.alerts.includes(dev.device_id) ? 'bg-red-900/50 border-red-500' : 'bg-gray-800/80 border-gray-700 hover:border-blue-500'">
                    <div class="text-sm font-bold text-white">{{ dev.name }}</div>
                    <div class="text-xs text-gray-400 mt-1 flex justify-between">
                        <span>ID: {{ dev.device_id }}</span>
                        <span :class="store.telemetry[dev.device_id]?.status === '離線' ? 'text-gray-500' : 'text-green-400'">
                            {{ store.telemetry[dev.device_id]?.status || '未知' }}
                        </span>
                    </div>
                </div>
            </div>

            <div v-if="selectedDevice" class="absolute bottom-8 left-[280px] w-96 bg-black border border-gray-700 rounded-lg shadow-2xl overflow-hidden z-30 transition-all">
                <div class="bg-gray-800 px-4 py-2 flex justify-between items-center border-b border-gray-700">
                    <span class="font-bold text-sm text-blue-400">🔴 {{ selectedDevice.name }} (現場畫面)</span>
                    <button @click="selectedDevice = null" class="text-gray-400 hover:text-white transition-colors">✕</button>
                </div>
                <div class="aspect-video bg-gray-900 flex items-center justify-center relative">
                    <img :src="selectedDevice.mjpeg_url" alt="MJPEG Stream" class="w-full h-full object-cover" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <div class="hidden flex-col items-center justify-center text-gray-500 text-sm absolute w-full h-full bg-gray-900">
                        <span>等待 NVR 影像接入...</span>
                        <span class="text-xs text-gray-600 font-mono mt-1">{{ selectedDevice.mjpeg_url }}</span>
                    </div>
                </div>
            </div>

            <div class="absolute bottom-24 right-8 z-20 flex flex-col bg-gray-900 border border-gray-700 rounded-lg shadow-2xl overflow-hidden">
                <button @click="goHome" title="回到初始視角" class="p-3 text-gray-400 hover:bg-gray-800 hover:text-white border-b border-gray-700 transition-colors">🏠</button>
                <button @click="resetCompass" title="重置指南針 (朝向正北)" class="p-3 text-gray-400 hover:bg-gray-800 hover:text-white border-b border-gray-700 transition-colors">🧭</button>
                <button @click="zoomIn" title="放大" class="p-3 text-xl font-bold text-gray-400 hover:bg-gray-800 hover:text-white border-b border-gray-700 transition-colors">＋</button>
                <button @click="zoomOut" title="縮小" class="p-3 text-xl font-bold text-gray-400 hover:bg-gray-800 hover:text-white transition-colors">－</button>
            </div>

            <div class="absolute bottom-8 right-8 z-20 flex bg-gray-900 border border-gray-700 rounded-lg shadow-2xl overflow-hidden">
                <button @click="switchMapMode(false)" :class="!is3DMode ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-800'" class="px-6 py-2 text-sm font-bold transition-colors">2D 平面</button>
                <button @click="switchMapMode(true)" :class="is3DMode ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-800'" class="px-6 py-2 text-sm font-bold transition-colors">3D 城市</button>
            </div>
        </div>
    `,
    setup() {
        let viewer = null;
        let tileset3D = null;      
        let imagery2DLayer = null; 
        let mapClickHandler = null;
        let fenceEntities = []; // 存放動態繪製的電子圍籬實體
        
        const is3DMode = ref(false); 
        const selectedDevice = ref(null); 
        const GOOGLE_API_KEY = "AIzaSyBZaiXtcr3qNMPjxO1Lhm6tvxPLSWlnsDo"; 

        const initMap = async () => {
            if (viewer) return;
            
            // 初始化 Cesium Viewer
            viewer = new Cesium.Viewer('cesiumContainer', {
                baseLayerPicker: false, imageryProvider: false, 
                geocoder: false, homeButton: false, infoBox: false,
                navigationHelpButton: false, sceneModePicker: false, 
                timeline: false, animation: false, shouldAnimate: true,
                selectionIndicator: false // 關閉預設的綠色選取框
            });

            // 1. 載入 2D 街道底圖
            const baseMapProvider = new Cesium.UrlTemplateImageryProvider({
                url: 'https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}'
            });
            imagery2DLayer = viewer.imageryLayers.addImageryProvider(baseMapProvider);

            // 2. 嘗試載入 Google Earth 3D 建築
            try {
                Cesium.GoogleMaps.defaultApiKey = GOOGLE_API_KEY;
                tileset3D = await Cesium.createGooglePhotorealistic3DTileset();
                tileset3D.show = false; // 預設隱藏 (2D模式)
                viewer.scene.primitives.add(tileset3D);
            } catch (error) {
                console.warn("無法載入 Google 3D 模型", error);
            }

            // 初始視角定位
            goHome();

            // 3. 設定地圖點擊偵測 (點選設備 Marker 彈出影像)
            mapClickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
            mapClickHandler.setInputAction((click) => {
                const pickedObject = viewer.scene.pick(click.position);
                if (Cesium.defined(pickedObject) && pickedObject.id) {
                    const deviceId = pickedObject.id.id; 
                    const dev = store.devices.find(d => d.device_id === deviceId);
                    if (dev) {
                        focusDevice(dev); // 鎖定視角並彈出影像
                    }
                } else {
                    // 點擊地圖空白處，關閉影像浮窗並解除鎖定
                    selectedDevice.value = null;
                    viewer.trackedEntity = undefined; 
                }
            }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

            // 繪製初始的電子圍籬
            drawGeofences();
        };

        // ====== 動態繪製電子圍籬 ======
        const drawGeofences = () => {
            if (!viewer) return;
            
            // 清除舊的圍籬圖層
            fenceEntities.forEach(e => viewer.entities.remove(e));
            fenceEntities = [];

            // 依據 store 中的資料重新繪製
            store.geofences.forEach(fence => {
                if (fence.is_enabled) {
                    try {
                        const pts = JSON.parse(fence.points);
                        const degreesArray = pts.flatMap(p => [p.lng, p.lat]);
                        const entity = viewer.entities.add({
                            name: fence.name,
                            polygon: {
                                hierarchy: Cesium.Cartesian3.fromDegreesArray(degreesArray),
                                extrudedHeight: 150.0, // 3D 立體力場高度
                                material: Cesium.Color.RED.withAlpha(0.2), 
                                outline: true, 
                                outlineColor: Cesium.Color.RED
                            }
                        });
                        fenceEntities.push(entity);
                    } catch(e) {
                        console.error("解析警戒區座標失敗", e);
                    }
                }
            });
        };

        // ====== 地圖控制與切換功能 ======
        const zoomIn = () => { if (viewer) viewer.camera.zoomIn(viewer.camera.positionCartographic.height * 0.3); };
        const zoomOut = () => { if (viewer) viewer.camera.zoomOut(viewer.camera.positionCartographic.height * 0.3); };
        
        const goHome = () => {
            if (viewer) {
                viewer.trackedEntity = undefined; // 解除追蹤
                const pitch = is3DMode.value ? -45 : -90;
                viewer.camera.flyTo({ 
                    destination: Cesium.Cartesian3.fromDegrees(121.5644, 25.0330, is3DMode.value ? 1500.0 : 3000.0),
                    orientation: { heading: 0, pitch: Cesium.Math.toRadians(pitch), roll: 0 },
                    duration: 1.5
                });
            }
        };

        const resetCompass = () => {
            if (viewer) {
                viewer.camera.flyTo({
                    destination: viewer.camera.position,
                    orientation: { heading: 0, pitch: viewer.camera.pitch, roll: 0 },
                    duration: 1.0
                });
            }
        };

        const switchMapMode = (to3D) => {
            if (to3D && !tileset3D) {
                alert("3D 模型載入失敗或無權限！"); return;
            }
            is3DMode.value = to3D;
            if (to3D) {
                if (imagery2DLayer) imagery2DLayer.show = false;
                if (tileset3D) tileset3D.show = true;
                viewer.camera.flyTo({
                    destination: viewer.camera.position,
                    orientation: { heading: viewer.camera.heading, pitch: Cesium.Math.toRadians(-45), roll: 0 },
                    duration: 1.5 
                });
            } else {
                if (tileset3D) tileset3D.show = false;
                if (imagery2DLayer) imagery2DLayer.show = true;
                viewer.camera.flyTo({
                    destination: viewer.camera.position,
                    orientation: { heading: viewer.camera.heading, pitch: Cesium.Math.toRadians(-90), roll: 0 },
                    duration: 1.5
                });
            }
        };

        // ====== 設備標記與軌跡更新 ======
        const updateMarkers = () => {
            if (!viewer) return;
            const time = Cesium.JulianDate.now();
            for (const [deviceId, state] of Object.entries(store.telemetry)) {
                let entity = viewer.entities.getById(deviceId);
                
                // 處理設備離線
                if (state.status === '離線') {
                    if (entity) viewer.entities.remove(entity);
                    continue;
                }
                
                // 座標高度固定 15m，避免被 3D 地形遮擋
                let position = Cesium.Cartesian3.fromDegrees(state.lng, state.lat, 15);
                let baseColor = state.status === '錄影中' ? Cesium.Color.ORANGE : Cesium.Color.DODGERBLUE;
                // 如果設備在警報名單中，強制轉為紅色
                const markerColor = store.alerts.includes(deviceId) ? Cesium.Color.RED : baseColor;

                if (!entity) {
                    // 新設備：建立標記與發光軌跡
                    const positionProperty = new Cesium.SampledPositionProperty();
                    positionProperty.addSample(time, position);
                    viewer.entities.add({
                        id: deviceId, 
                        position: positionProperty,
                        point: { pixelSize: 15, color: markerColor, outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
                        label: { text: deviceId, font: '12pt sans-serif', fillColor: Cesium.Color.WHITE, style: Cesium.LabelStyle.FILL_AND_OUTLINE, verticalOrigin: Cesium.VerticalOrigin.BOTTOM, pixelOffset: new Cesium.Cartesian2(0, -20) },
                        path: { show: true, leadTime: 0, trailTime: 60, width: 4, resolution: 1, material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.3, color: markerColor }) }
                    });
                } else {
                    // 既有設備：更新座標與顏色
                    entity.position.addSample(time, position);
                    entity.point.color = markerColor; 
                    entity.path.material.color = markerColor;
                }
            }
        };

        // ====== 點擊設備觸發追蹤與影像 ======
        const focusDevice = (dev) => {
            selectedDevice.value = dev; 
            let entity = viewer?.entities.getById(dev.device_id);
            if (entity) {
                viewer.trackedEntity = entity;
                const pitch = is3DMode.value ? Cesium.Math.toRadians(-45) : Cesium.Math.toRadians(-90);
                viewer.zoomTo(entity, new Cesium.HeadingPitchRange(0, pitch, 500));
            }
        };

        // ====== 生命週期掛載與資料監聽 ======
        onMounted(() => { 
            initMap(); 
        });

        // 當收到新座標時，更新設備標記
        watch(() => store.telemetry, updateMarkers, { deep: true });
        
        // 當使用者新增或刪除電子圍籬時，重新繪製地圖上的力場
        watch(() => store.geofences, drawGeofences, { deep: true });

        // 元件卸載時銷毀地圖，釋放記憶體
        onUnmounted(() => {
            if (viewer) {
                if (mapClickHandler) mapClickHandler.destroy();
                viewer.destroy();
            }
        });

        return { 
            store, is3DMode, selectedDevice, 
            focusDevice, switchMapMode, zoomIn, zoomOut, goHome, resetCompass 
        };
    }
};