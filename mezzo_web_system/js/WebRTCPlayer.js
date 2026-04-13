// js/WebRTCPlayer.js  v5
// 核心原則：
//   1. 所有 DOM 元素放在 Vue template（讓 Vue 管理 vdom）
//   2. 用 Vue data() 控制狀態文字與顯示，用 $refs.vid 操作 srcObject
//   3. WebRTC 邏輯與 webrtc_test.html 完全一致
export default {
    name: 'WebRTCPlayer',
    props: {
        rtspUrl:  { type: String, default: '' },
        mjpegUrl: { type: String, default: '' }
    },
    data() {
        return {
            msg:      '連線中…',
            isError:  false,
            playing:  false
        };
    },
    template: `
        <div style="width:100%;height:100%;position:relative;background:#000;overflow:hidden;">
            <video ref="vid" autoplay playsinline muted
                   style="width:100%;height:100%;object-fit:contain;display:block;"></video>
            <div v-if="!playing"
                 style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.75);padding:8px;text-align:center;">
                <span :style="{color: isError ? '#f66' : '#ff0', fontSize:'12px'}">
                    {{ isError ? '❌ ' : '⏳ ' }}{{ msg }}
                </span>
            </div>
            <div v-else
                 style="position:absolute;bottom:4px;right:4px;font-size:9px;padding:2px 5px;border-radius:3px;background:rgba(0,180,0,0.8);color:#fff;pointer-events:none;">
                WebRTC ●
            </div>
        </div>
    `,
    mounted() {
        this._go();
    },
    beforeUnmount() {
        this._cleanup();
    },
    watch: {
        rtspUrl()  { this._restart(); },
        mjpegUrl() { this._restart(); }
    },
    methods: {
        _restart() {
            this._cleanup();
            this.msg     = '重新連線…';
            this.isError = false;
            this.playing = false;
            this._go();
        },
        _cleanup() {
            if (this._pc) { this._pc.close(); this._pc = null; }
            const vid = this.$refs.vid;
            if (vid) vid.srcObject = null;
            if (this._pcId) {
                fetch((window.MEZZO_BASE || '') + '/api/webrtc/' + this._pcId, { method: 'DELETE' }).catch(() => {});
                this._pcId = null;
            }
        },

        // ── WebRTC 邏輯（與 webrtc_test.html 完全一致） ──
        async _go() {
            const rtspUrl  = this.rtspUrl;
            const mjpegUrl = this.mjpegUrl;

            if (!rtspUrl && !mjpegUrl) {
                this.msg = '無串流 URL'; this.isError = true; return;
            }

            const vid = this.$refs.vid;
            if (!vid) {
                this.msg = '播放器未就緒'; this.isError = true; return;
            }

            try {
                const pc = new RTCPeerConnection({
                    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
                });
                this._pc = pc;

                pc.addTransceiver('video', { direction: 'recvonly' });

                pc.ontrack = (event) => {
                    vid.srcObject = event.streams?.[0] || new MediaStream([event.track]);
                    vid.play()
                        .then(() => { this.playing = true; })
                        .catch(() => { this.playing = true; });
                };

                pc.oniceconnectionstatechange = () => {
                    const s = pc.iceConnectionState;
                    if (s === 'failed')       { this.msg = 'ICE 失敗'; this.isError = true; this.playing = false; }
                    else if (s === 'disconnected') { this.msg = '連線中斷'; this.isError = true; this.playing = false; }
                };

                pc.onconnectionstatechange = () => {
                    if (pc.connectionState === 'failed') { this.msg = '連線失敗'; this.isError = true; this.playing = false; }
                };

                // Create offer
                this.msg = '建立連線…';
                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);

                // Wait ICE gathering (max 6 s)
                this.msg = 'ICE 蒐集中…';
                await new Promise(resolve => {
                    if (pc.iceGatheringState === 'complete') return resolve();
                    pc.addEventListener('icegatheringstatechange', () => {
                        if (pc.iceGatheringState === 'complete') resolve();
                    });
                    setTimeout(resolve, 6000);
                });

                // POST offer
                this.msg = '傳送至伺服器…';
                const res = await fetch((window.MEZZO_BASE || '') + '/api/webrtc/offer', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({
                        sdp:       pc.localDescription.sdp,
                        type:      pc.localDescription.type,
                        rtsp_url:  rtspUrl,
                        mjpeg_url: mjpegUrl
                    })
                });

                if (!res.ok) {
                    const e = await res.json().catch(() => ({}));
                    throw new Error(e?.detail || 'HTTP ' + res.status);
                }

                const ans = await res.json();
                this._pcId = ans.pc_id;

                this.msg = '協商中…';
                await pc.setRemoteDescription(new RTCSessionDescription({
                    sdp:  ans.sdp,
                    type: ans.type
                }));

            } catch (e) {
                this.msg = e.message || '未知錯誤';
                this.isError = true;
            }
        }
    }
};
