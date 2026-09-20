/* DexterPhone Desktop - Production Grade */

const dom = {
    authPanel: document.getElementById('auth-panel'),
    dialerPanel: document.getElementById('dialer-panel'),
    hardwarePanel: document.getElementById('hardware-panel'),
    extInput: document.getElementById('sip-ext'),
    pwdInput: document.getElementById('sip-pwd'),
    btnSave: document.getElementById('btn-save-settings'),
    
    statusDot: document.getElementById('status-dot'),
    statusText: document.getElementById('status-text'),
    
    dialInput: document.getElementById('dial-input'),
    btnDial: document.getElementById('btn-dial-call'),
    btnClear: document.getElementById('btn-dial-clear'),
    
    audioIn: document.getElementById('audio-input-select'),
    audioOut: document.getElementById('audio-output-select'),
    
    callsContainer: document.getElementById('calls-container'),
    emptyState: document.getElementById('empty-state'),
    
    incomingModal: document.getElementById('incoming-modal'),
    incomingName: document.getElementById('incoming-name'),
    btnAccept: document.getElementById('btn-accept'),
    btnReject: document.getElementById('btn-reject'),
    
    tplCallCard: document.getElementById('tpl-call-card')
};

let userAgent = null;
let registerer = null;
let activeCalls = new Map(); // session -> { card, timer, startTime }
let incomingSession = null;
let audioContext = null;

// Initialization
document.addEventListener('DOMContentLoaded', async () => {
    await loadAudioDevices();
    navigator.mediaDevices.ondevicechange = loadAudioDevices;
    
    const savedExt = localStorage.getItem('dxt_ext');
    const savedPwd = localStorage.getItem('dxt_pwd');
    if (savedExt && savedPwd) {
        dom.extInput.value = savedExt;
        dom.pwdInput.value = savedPwd;
        initSIP();
    }
});

dom.btnSave.onclick = () => {
    localStorage.setItem('dxt_ext', dom.extInput.value);
    localStorage.setItem('dxt_pwd', dom.pwdInput.value);
    initSIP();
};

async function loadAudioDevices() {
    try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        dom.audioIn.innerHTML = ''; dom.audioOut.innerHTML = '';
        devices.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.deviceId; opt.text = d.label || `${d.kind} (${d.deviceId.slice(0, 5)})`;
            if (d.kind === 'audioinput') dom.audioIn.appendChild(opt);
            else if (d.kind === 'audiooutput') dom.audioOut.appendChild(opt);
        });
    } catch (e) {
        console.error("Mic access denied");
    }
}

// SIP Core
function initSIP() {
    const ext = dom.extInput.value;
    const pwd = dom.pwdInput.value;
    if (!ext || !pwd) return;
    
    if (userAgent) { userAgent.stop(); }
    
    const domain = window.location.hostname;
    const uri = SIP.UserAgent.makeURI(`sip:${ext}@${domain}`);
    
    userAgent = new SIP.UserAgent({
        uri: uri,
        authorizationUsername: ext,
        authorizationPassword: pwd,
        transportOptions: { server: `wss://${domain}/ws` },
        sessionDescriptionHandlerFactoryOptions: {
            peerConnectionOptions: { rtcConfiguration: { sdpSemantics: 'unified-plan' } }
        }
    });
    
    userAgent.transport.onConnect = () => {
        dom.statusDot.className = 'pulse-dot bg-success';
        dom.statusText.innerText = 'Connected & Registered';
        dom.authPanel.classList.add('hidden');
        dom.dialerPanel.classList.remove('hidden');
        dom.hardwarePanel.classList.remove('hidden');
    };
    
    userAgent.transport.onDisconnect = () => {
        dom.statusDot.className = 'pulse-dot bg-danger';
        dom.statusText.innerText = 'Reconnecting...';
        
        // Cleanup all calls safely
        for (let [session, data] of activeCalls) {
            terminateCall(session);
        }
        if (incomingSession) {
            incomingSession = null;
            dom.incomingModal.classList.add('hidden');
            document.getElementById('ringing-audio').pause();
        }
    };
    
    userAgent.delegate = {
        onInvite: (invitation) => {
            document.getElementById('ringing-audio').play();
            incomingSession = invitation;
            dom.incomingName.innerText = invitation.remoteIdentity.displayName || invitation.remoteIdentity.uri.user;
            dom.incomingModal.classList.remove('hidden');
            
            invitation.stateChange.addListener((state) => {
                if (state === SIP.SessionState.Terminated) {
                    document.getElementById('ringing-audio').pause();
                    dom.incomingModal.classList.add('hidden');
                    incomingSession = null;
                }
            });
        }
    };
    
    registerer = new SIP.Registerer(userAgent);
    userAgent.start().then(() => registerer.register());
}

// Dialpad Logic
document.querySelectorAll('.dial-key').forEach(btn => {
    btn.onclick = () => { dom.dialInput.value += btn.getAttribute('data-key'); playDTMF(); };
});
dom.btnClear.onclick = () => { dom.dialInput.value = dom.dialInput.value.slice(0, -1); };

function playDTMF() { /* Optional beep */ }

// Make Call
dom.btnDial.onclick = () => {
    const target = dom.dialInput.value;
    if (!target || !userAgent) return;
    
    const uri = SIP.UserAgent.makeURI(`sip:${target}@${window.location.hostname}`);
    const inviter = new SIP.Inviter(userAgent, uri);
    
    setupSession(inviter, target, 'Outgoing');
    
    const constraints = dom.audioIn.value ? { audio: { deviceId: { exact: dom.audioIn.value } } } : { audio: true };
    inviter.invite({ sessionDescriptionHandlerOptions: { constraints: constraints } });
    
    document.getElementById('ringback-audio').play();
    dom.dialInput.value = '';
};

// Accept Call
dom.btnAccept.onclick = async () => {
    document.getElementById('ringing-audio').pause();
    dom.incomingModal.classList.add('hidden');
    
    if (!incomingSession) return;
    
    // Put other active calls on hold automatically
    for (let [session, data] of activeCalls) {
        if (!data.held) await toggleHold(session, true);
    }
    
    const session = incomingSession;
    incomingSession = null;
    
    setupSession(session, session.remoteIdentity.displayName || session.remoteIdentity.uri.user, 'Incoming');
    
    const constraints = dom.audioIn.value ? { audio: { deviceId: { exact: dom.audioIn.value } } } : { audio: true };
    session.accept({ sessionDescriptionHandlerOptions: { constraints: constraints } });
};

dom.btnReject.onclick = () => {
    document.getElementById('ringing-audio').pause();
    dom.incomingModal.classList.add('hidden');
    if (incomingSession) { incomingSession.reject(); incomingSession = null; }
};

// Session Management
function setupSession(session, displayName, direction) {
    dom.emptyState.classList.add('hidden');
    
    const clone = dom.tplCallCard.content.cloneNode(true);
    const card = clone.querySelector('.call-card');
    card.dataset.sessionId = session.id;
    
    card.querySelector('.caller-name').innerText = displayName;
    dom.callsContainer.prepend(card);
    
    const callData = {
        card: card,
        held: false,
        timer: null,
        startTime: null,
        audioElement: document.createElement('audio')
    };
    callData.audioElement.autoplay = true;
    if (dom.audioOut.value && typeof callData.audioElement.setSinkId !== 'undefined') {
        callData.audioElement.setSinkId(dom.audioOut.value);
    }
    activeCalls.set(session, callData);
    
    bindSessionEvents(session, callData);
    bindCardUI(session, callData);
}

function bindSessionEvents(session, callData) {
    session.stateChange.addListener((state) => {
        const statusBadge = callData.card.querySelector('.call-status');
        
        if (state === SIP.SessionState.Establishing) {
            statusBadge.innerText = "Connecting...";
        } 
        else if (state === SIP.SessionState.Established) {
            document.getElementById('ringback-audio').pause();
            statusBadge.innerText = "Active Call";
            statusBadge.className = "call-status badge bg-success";
            callData.card.classList.add('active');
            
            // Attach Audio
            const pc = session.sessionDescriptionHandler.peerConnection;
            const remoteStream = new MediaStream();
            pc.getReceivers().forEach(r => { if(r.track) remoteStream.addTrack(r.track); });
            callData.audioElement.srcObject = remoteStream;
            
            // Start Timer
            callData.startTime = Date.now();
            callData.timer = setInterval(() => {
                const diff = Math.floor((Date.now() - callData.startTime) / 1000);
                const m = String(Math.floor(diff / 60)).padStart(2, '0');
                const s = String(diff % 60).padStart(2, '0');
                callData.card.querySelector('.call-timer').innerHTML = `<i class="fa-regular fa-clock"></i> ${m}:${s}`;
                updateStats(session, callData);
            }, 1000);
            
            updateMergeVisibility();
        } 
        else if (state === SIP.SessionState.Terminated) {
            document.getElementById('ringback-audio').pause();
            terminateCall(session);
        }
    });
}

function terminateCall(session) {
    const data = activeCalls.get(session);
    if (!data) return;
    
    clearInterval(data.timer);
    data.audioElement.pause();
    data.audioElement.remove();
    data.card.remove();
    activeCalls.delete(session);
    
    // Auto-resume if only 1 held call left
    if (activeCalls.size === 1) {
        const onlySession = Array.from(activeCalls.keys())[0];
        if (activeCalls.get(onlySession).held) {
            toggleHold(onlySession, false);
        }
    }
    
    if (activeCalls.size === 0) {
        dom.emptyState.classList.remove('hidden');
    }
    updateMergeVisibility();
}

// UI Bindings per Card
function bindCardUI(session, callData) {
    const card = callData.card;
    
    card.querySelector('.btn-end').onclick = () => {
        if (session.state === SIP.SessionState.Established) session.bye();
        else if (session.state === SIP.SessionState.Establishing) session.cancel();
    };
    
    card.querySelector('.btn-mute').onclick = (e) => {
        const pc = session.sessionDescriptionHandler.peerConnection;
        const senders = pc.getSenders().filter(s => s.track && s.track.kind === 'audio');
        const isMuted = e.target.classList.contains('muted');
        senders.forEach(s => s.track.enabled = isMuted);
        e.target.classList.toggle('muted');
    };
    
    card.querySelector('.btn-hold').onclick = () => toggleHold(session);
    
    // Transfer logic
    const tSheet = card.querySelector('.transfer-sheet');
    card.querySelector('.btn-transfer-toggle').onclick = () => tSheet.classList.toggle('hidden');
    card.querySelector('.btn-cancel-transfer').onclick = () => tSheet.classList.add('hidden');
    
    card.querySelector('.btn-blind-transfer').onclick = () => {
        const target = tSheet.querySelector('.transfer-target').value;
        if (!target) return;
        const uri = SIP.UserAgent.makeURI(`sip:${target}@${window.location.hostname}`);
        session.refer(uri);
        tSheet.classList.add('hidden');
    };
    
    card.querySelector('.btn-attended-transfer').onclick = () => {
        let otherSession = null;
        for (let [s, d] of activeCalls) { if (s !== session) otherSession = s; }
        if (!otherSession) { alert("Requires another call"); return; }
        session.refer(otherSession);
        tSheet.classList.add('hidden');
    };
    
    // Merge Logic
    card.querySelector('.btn-merge').onclick = async () => {
        if (activeCalls.size < 2) return;
        const s1 = Array.from(activeCalls.keys())[0];
        const s2 = Array.from(activeCalls.keys())[1];
        
        await toggleHold(s1, false);
        await toggleHold(s2, false);
        
        // Native Web Audio Mix-Minus Bridge
        const ac = new (window.AudioContext || window.webkitAudioContext)();
        const src1 = ac.createMediaStreamSource(activeCalls.get(s1).audioElement.srcObject);
        const src2 = ac.createMediaStreamSource(activeCalls.get(s2).audioElement.srcObject);
        
        const constraints = dom.audioIn.value ? { audio: { deviceId: { exact: dom.audioIn.value } } } : { audio: true };
        const localStream = await navigator.mediaDevices.getUserMedia(constraints);
        const srcLocal = ac.createMediaStreamSource(localStream);
        
        const dest1 = ac.createMediaStreamDestination();
        const dest2 = ac.createMediaStreamDestination();
        
        srcLocal.connect(dest1); src2.connect(dest1);
        srcLocal.connect(dest2); src1.connect(dest2);
        
        const sender1 = s1.sessionDescriptionHandler.peerConnection.getSenders().find(s => s.track && s.track.kind === 'audio');
        if (sender1) sender1.replaceTrack(dest1.stream.getAudioTracks()[0]);
        
        const sender2 = s2.sessionDescriptionHandler.peerConnection.getSenders().find(s => s.track && s.track.kind === 'audio');
        if (sender2) sender2.replaceTrack(dest2.stream.getAudioTracks()[0]);
        
        document.querySelectorAll('.call-status').forEach(el => {
            el.innerText = "Conference"; el.className = "call-status badge bg-primary";
        });
    };
}

async function toggleHold(session, forceState) {
    const data = activeCalls.get(session);
    if (!data) return;
    
    const shouldHold = forceState !== undefined ? forceState : !data.held;
    const btn = data.card.querySelector('.btn-hold');
    const status = data.card.querySelector('.call-status');
    
    if (shouldHold) {
        data.held = true;
        btn.classList.add('held');
        data.card.classList.remove('active');
        data.card.classList.add('held');
        status.innerText = "On Hold";
        status.className = "call-status badge bg-warning-soft";
        
        await session.invite({ sessionDescriptionHandlerModifiers: [
            (desc) => { desc.sdp = desc.sdp.replace(/a=sendrecv/g, 'a=sendonly'); return Promise.resolve(desc); }
        ]});
    } else {
        data.held = false;
        btn.classList.remove('held');
        data.card.classList.add('active');
        data.card.classList.remove('held');
        status.innerText = "Active Call";
        status.className = "call-status badge bg-success";
        
        await session.invite({ sessionDescriptionHandlerModifiers: [
            (desc) => { desc.sdp = desc.sdp.replace(/a=sendonly/g, 'a=sendrecv'); return Promise.resolve(desc); }
        ]});
    }
}

function updateMergeVisibility() {
    const show = activeCalls.size >= 2;
    document.querySelectorAll('.btn-merge').forEach(b => {
        if (show) b.classList.remove('hidden'); else b.classList.add('hidden');
    });
}

// Diagnostics
async function updateStats(session, data) {
    if (session.state !== SIP.SessionState.Established) return;
    const pc = session.sessionDescriptionHandler.peerConnection;
    const stats = await pc.getStats();
    let jitter = 0, loss = 0, rtt = 0;
    
    stats.forEach(report => {
        if (report.type === 'inbound-rtp' && report.kind === 'audio') {
            jitter = (report.jitter * 1000).toFixed(1);
            loss = report.packetsLost || 0;
        }
        if (report.type === 'candidate-pair' && report.state === 'succeeded') {
            rtt = (report.currentRoundTripTime * 1000).toFixed(0);
        }
    });
    
    data.card.querySelector('.stat-jitter').innerText = `Jitter: ${jitter}ms`;
    data.card.querySelector('.stat-loss').innerText = `Loss: ${loss}`;
    data.card.querySelector('.stat-rtt').innerText = `RTT: ${rtt}ms`;
    data.card.querySelector('.stat-ice').innerText = `ICE: ${pc.iceConnectionState}`;
}
