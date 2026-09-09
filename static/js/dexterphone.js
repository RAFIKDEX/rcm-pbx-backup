// DEXTER Phone WebRTC - Core Engine
let userAgent = null;
let calls = new Map();
let activeCallId = null;

// Audio elements
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
let ringtoneInterval = null;
let ringbackInterval = null;

// UI Elements
const els = {
    screenLogin: document.getElementById('screen-login'),
    screenDialer: document.getElementById('screen-dialer'),
    callContainer: document.getElementById('calls-container'),
    dialInput: document.getElementById('dial-input'),
    statusText: document.getElementById('status-text')
};

function playTone(freq, type='sine', dur=100) {
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.00001, audioCtx.currentTime + (dur/1000));
    osc.stop(audioCtx.currentTime + (dur/1000));
}

function playRingtone() {
    if (ringtoneInterval) return;
    ringtoneInterval = setInterval(() => {
        playTone(440, 'sine', 1000);
        setTimeout(() => playTone(480, 'sine', 1000), 200);
    }, 2000);
}
function stopRingtone() {
    clearInterval(ringtoneInterval);
    ringtoneInterval = null;
}
function playRingback() {
    if (ringbackInterval) return;
    ringbackInterval = setInterval(() => {
        playTone(440, 'sine', 2000);
        setTimeout(() => playTone(480, 'sine', 2000), 200);
    }, 4000);
}
function stopRingback() {
    clearInterval(ringbackInterval);
    ringbackInterval = null;
}

class CallSession {
    constructor(session, isIncoming) {
        this.id = session.request ? session.request.callId : Math.random().toString();
        this.session = session;
        this.isIncoming = isIncoming;
        this.target = isIncoming ? session.remoteIdentity.uri.user : session.request.to.uri.user;
        this.state = isIncoming ? 'INCOMING' : 'CONNECTING';
        this.timer = 0;
        this.timerInterval = null;
        this.isHeld = false;
        this.isMuted = false;
        
        // Dedicated audio element for this call
        this.audioEl = new Audio();
        this.audioEl.autoplay = true;

        this.setupEvents();
    }

    setupEvents() {
        this.session.stateChange.addListener((state) => {
            console.log(`Call ${this.id} state changed to:`, state);
            if (state === SIP.SessionState.Establishing) {
                if (!this.isIncoming) {
                    this.state = 'RINGING';
                    playRingback();
                }
            } 
            else if (state === SIP.SessionState.Established) {
                stopRingback();
                stopRingtone();
                this.state = 'CONNECTED';
                if (!this.timerInterval) {
                    this.timerInterval = setInterval(() => { this.timer++; renderCalls(); }, 1000);
                }
                
                // Attach remote media
                const pc = this.session.sessionDescriptionHandler.peerConnection;
                const remoteStream = new MediaStream();
                pc.getReceivers().forEach(receiver => {
                    if (receiver.track) remoteStream.addTrack(receiver.track);
                });
                this.audioEl.srcObject = remoteStream;
                this.audioEl.play().catch(e => console.error('Audio play error', e));
            }
            else if (state === SIP.SessionState.Terminated) {
                stopRingback();
                stopRingtone();
                clearInterval(this.timerInterval);
                this.audioEl.srcObject = null;
                calls.delete(this.id);
                if (activeCallId === this.id) {
                    // Try to fall back to another call if available
                    const remaining = Array.from(calls.keys());
                    activeCallId = remaining.length > 0 ? remaining[0] : null;
                }
                renderCalls();
            }
            renderCalls();
        });
    }

    answer() {
        stopRingtone();
        this.session.accept({
            sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } }
        }).catch(e => {
            console.error('Answer failed', e);
            this.session.reject();
        });
    }

    reject() {
        stopRingtone();
        this.session.reject();
    }

    hangup() {
        if (this.session.state === SIP.SessionState.Establishing) {
            if (this.session instanceof SIP.Inviter) this.session.cancel();
            else this.session.reject();
        } else {
            this.session.bye();
        }
    }

    toggleMute() {
        const pc = this.session.sessionDescriptionHandler.peerConnection;
        if (!pc) return;
        pc.getSenders().forEach(sender => {
            if (sender.track && sender.track.kind === 'audio') {
                sender.track.enabled = !sender.track.enabled;
                this.isMuted = !sender.track.enabled;
            }
        });
        renderCalls();
    }

    toggleHold() {
        if (!this.session || this.state !== 'CONNECTED') return;
        const options = {
            sessionDescriptionHandlerModifiers: [
                (sd) => {
                    if (this.isHeld) {
                        sd.sdp = sd.sdp.replace(/a=sendonly/g, 'a=sendrecv').replace(/a=inactive/g, 'a=sendrecv');
                    } else {
                        sd.sdp = sd.sdp.replace(/a=sendrecv/g, 'a=sendonly');
                    }
                    return Promise.resolve(sd);
                }
            ]
        };
        this.session.invite(options).then(() => {
            this.isHeld = !this.isHeld;
            renderCalls();
        });
    }
    
    sendDTMF(digit) {
        try {
            const pc = this.session.sessionDescriptionHandler.peerConnection;
            const senders = pc.getSenders();
            let sent = false;
            for (let sender of senders) {
                if (sender.dtmf) {
                    sender.dtmf.insertDTMF(digit);
                    sent = true; break;
                }
            }
            if (!sent) {
                const dtmf = new SIP.Infoer(this.session, 'application/dtmf-relay');
                dtmf.send({ body: `Signal=${digit}\r\nDuration=160` });
            }
        } catch(e) { console.error('DTMF Error', e); }
    }
}

function formatTime(sec) {
    const m = Math.floor(sec / 60).toString().padStart(2, '0');
    const s = (sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

function renderCalls() {
    els.callContainer.innerHTML = '';
    
    if (calls.size === 0) {
        els.screenDialer.style.display = 'flex';
        els.callContainer.style.display = 'none';
        return;
    }
    
    els.screenDialer.style.display = 'none';
    els.callContainer.style.display = 'flex';

    calls.forEach((call, id) => {
        const isActive = activeCallId === id;
        const card = document.createElement('div');
        card.className = `call-card ${isActive ? 'active' : 'background'}`;
        card.onclick = () => { if (!isActive) swapCall(id); };
        
        let actionsHtml = '';
        if (call.state === 'INCOMING') {
            actionsHtml = `
                <button class="btn btn-success" onclick="event.stopPropagation(); calls.get('${id}').answer()">Answer</button>
                <button class="btn btn-danger" onclick="event.stopPropagation(); calls.get('${id}').reject()">Reject</button>
            `;
        } else {
            actionsHtml = `
                <button class="btn btn-dark ${call.isMuted ? 'text-danger' : ''}" onclick="event.stopPropagation(); calls.get('${id}').toggleMute()">Mute</button>
                <button class="btn btn-dark ${call.isHeld ? 'text-warning' : ''}" onclick="event.stopPropagation(); calls.get('${id}').toggleHold()">${call.isHeld ? 'Resume' : 'Hold'}</button>
                <button class="btn btn-dark" onclick="event.stopPropagation(); transferMenu('${id}')">Blind Xfer</button>
                <button class="btn btn-dark" onclick="event.stopPropagation(); attendedTransfer('${id}')">Att Xfer</button>
                <button class="btn btn-danger" onclick="event.stopPropagation(); calls.get('${id}').hangup()">End</button>
            `;
        }

        card.innerHTML = `
            <div class="call-info">
                <h3>${call.target}</h3>
                <p>${call.state === 'CONNECTED' ? formatTime(call.timer) : call.state}</p>
                ${call.isHeld ? '<span class="badge bg-warning">HELD</span>' : ''}
            </div>
            <div class="call-actions" style="display: ${isActive ? 'flex' : 'none'}">
                ${actionsHtml}
            </div>
        `;
        els.callContainer.appendChild(card);
    });
}

function swapCall(newActiveId) {
    // Hold current active if connected and not held
    if (activeCallId && calls.has(activeCallId)) {
        const curr = calls.get(activeCallId);
        if (curr.state === 'CONNECTED' && !curr.isHeld) {
            curr.toggleHold();
        }
    }
    activeCallId = newActiveId;
    // Resume new active if held
    const next = calls.get(newActiveId);
    if (next && next.isHeld) {
        next.toggleHold();
    }
    renderCalls();
}

async function connectSIP(ext, pwd) {
    els.statusText.innerText = "Connecting...";
    try {
        const srv = window.location.hostname;
        const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsServer = `${wsProtocol}://${srv}/ws`;

        const transportOptions = { server: wsServer, connectionTimeout: 10, keepAliveInterval: 30 };
        const uri = SIP.UserAgent.makeURI(`sip:${ext}@${srv}`);
        
        userAgent = new SIP.UserAgent({
            uri: uri,
            transportOptions: transportOptions,
            authorizationUsername: ext,
            authorizationPassword: pwd,
            sessionDescriptionHandlerFactoryOptions: {
                peerConnectionOptions: { rtcConfiguration: { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] } }
            }
        });

        userAgent.stateChange.addListener(state => {
            if (state === SIP.UserAgentState.Started) {
                els.statusText.innerText = `Registered as ${ext}`;
                els.screenLogin.style.display = 'none';
                els.screenDialer.style.display = 'flex';
            } else if (state === SIP.UserAgentState.Stopped) {
                els.statusText.innerText = "Offline";
                els.screenLogin.style.display = 'flex';
                els.screenDialer.style.display = 'none';
            }
        });

        userAgent.transport.onConnect = () => userAgent.register.register();
        userAgent.transport.onDisconnect = () => console.warn('WSS Disconnected');

        userAgent.delegate = {
            onInvite: (invitation) => {
                const call = new CallSession(invitation, true);
                calls.set(call.id, call);
                if (!activeCallId) activeCallId = call.id;
                playRingtone();
                renderCalls();
            }
        };

        await userAgent.start();
        
    } catch (e) {
        els.statusText.innerText = "Error: " + e.message;
    }
}

function dialNumber() {
    const target = els.dialInput.value.trim();
    if (!target || !userAgent) return;
    const uri = SIP.UserAgent.makeURI(`sip:${target}@${window.location.hostname}`);
    const inviter = new SIP.Inviter(userAgent, uri, {
        sessionDescriptionHandlerOptions: { constraints: { audio: true, video: false } }
    });
    const call = new CallSession(inviter, false);
    
    // Hold active call before dialing new one
    if (activeCallId && calls.has(activeCallId)) {
        const curr = calls.get(activeCallId);
        if (curr.state === 'CONNECTED' && !curr.isHeld) curr.toggleHold();
    }
    
    calls.set(call.id, call);
    activeCallId = call.id;
    inviter.invite().catch(e => { console.error('Dial error', e); calls.delete(call.id); renderCalls(); });
    els.dialInput.value = '';
    renderCalls();
}

function pressDigit(d) {
    playTone(440 + (Math.random()*100), 'sine', 100);
    if (activeCallId && calls.has(activeCallId) && calls.get(activeCallId).state === 'CONNECTED') {
        calls.get(activeCallId).sendDTMF(d);
    } else {
        els.dialInput.value += d;
    }
}

function transferMenu(callId) {
    const target = prompt("Enter extension to transfer to:");
    if (!target) return;
    const call = calls.get(callId);
    if (!call) return;
    
    const targetURI = SIP.UserAgent.makeURI(`sip:${target}@${window.location.hostname}`);
    call.session.refer(targetURI).then(() => {
        console.log("Blind transfer sent");
        // Asterisk will hang us up automatically
    }).catch(e => {
        alert("Transfer failed: " + e.message);
    });
}

document.getElementById('btn-connect').onclick = () => {
    const ext = document.getElementById('sip-ext').value;
    const pwd = document.getElementById('sip-pwd').value;
    localStorage.setItem('dexter_ext', ext);
    connectSIP(ext, pwd);
};

if (localStorage.getItem('dexter_ext')) {
    document.getElementById('sip-ext').value = localStorage.getItem('dexter_ext');
}

function attendedTransfer(callId) {
    const callA = calls.get(callId);
    if (!callA) return;
    
    // Find another connected call
    let callB = null;
    for (let [id, c] of calls.entries()) {
        if (id !== callId && c.state === 'CONNECTED') {
            callB = c;
            break;
        }
    }
    
    if (!callB) {
        alert("You need a second connected call to perform an attended transfer.");
        return;
    }
    
    if (confirm(`Transfer ${callA.target} to ${callB.target}?`)) {
        callA.session.refer(callB.session).then(() => {
            console.log("Attended transfer successful");
        }).catch(e => alert("Transfer failed: " + e.message));
    }
}
