
const dom = {
    themeBtn: document.getElementById('btn-theme-toggle'),
    statusPill: document.getElementById('conn-status-pill'),
    statusText: document.getElementById('conn-status-text'),
    uriDisplay: document.getElementById('sip-uri-display'),
    
    viewDialer: document.getElementById('view-dialer'),
    viewCalls: document.getElementById('view-calls'),
    
    dialInput: document.getElementById('dial-input'),
    btnDial: document.getElementById('btn-dial-call'),
    btnClear: document.getElementById('btn-dial-clear'),
    
    settingsModal: document.getElementById('settings-modal'),
    btnSaveSettings: document.getElementById('btn-save-settings'),
    
    incomingModal: document.getElementById('incoming-modal'),
    incomingInfo: document.getElementById('incoming-info'),
    btnAccept: document.getElementById('btn-accept'),
    btnReject: document.getElementById('btn-reject'),
    
    activeCallerName: document.getElementById('active-caller-name'),
    activeCallStatus: document.getElementById('active-call-status'),
    activeCallTimer: document.getElementById('active-call-timer'),
    
    multiCallIsland: document.getElementById('multi-call-island'),
    islandHeldName: document.getElementById('island-held-name'),
    btnIslandEnd: document.getElementById('btn-island-end'),
    btnIslandSwap: document.getElementById('btn-island-swap'),
    btnIslandMerge: document.getElementById('btn-island-merge'),
    
    transferSheet: document.getElementById('transfer-sheet'),
    transferTarget: document.getElementById('transfer-target'),
    btnBlindTransfer: document.getElementById('btn-blind-transfer'),
    btnAttendedTransfer: document.getElementById('btn-attended-transfer'),
    btnCancelTransfer: document.getElementById('btn-cancel-transfer'),
    
    btnMute: document.getElementById('btn-mute'),
    btnKeypad: document.getElementById('btn-keypad'),
    btnHold: document.getElementById('btn-hold'),
    btnTransfer: document.getElementById('btn-transfer'),
    btnAddCall: document.getElementById('btn-add-call'),
    btnEnd: document.getElementById('btn-end'),
    
    inCallKeypad: document.getElementById('in-call-keypad'),
    audioInput: document.getElementById('audio-input-select'),
    audioOutput: document.getElementById('audio-output-select')
};

let userAgent = null;
let registerer = null;
let activeSession = null;
let heldSession = null;
let incomingSession = null;
let callTimer = null;
let callStartTime = null;
const remoteAudios = new Map();

document.addEventListener('DOMContentLoaded', async () => {
    await loadAudioDevices();
    navigator.mediaDevices.ondevicechange = loadAudioDevices;
    
    if (localStorage.getItem('dxt_ext')) {
        document.getElementById('sip-ext').value = localStorage.getItem('dxt_ext');
        document.getElementById('sip-pwd').value = localStorage.getItem('dxt_pwd');
        initSIP();
    }
});

dom.btnSaveSettings.onclick = () => {
    localStorage.setItem('dxt_ext', document.getElementById('sip-ext').value);
    localStorage.setItem('dxt_pwd', document.getElementById('sip-pwd').value);
    initSIP();
};

async function loadAudioDevices() {
    try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        dom.audioInput.innerHTML = ''; dom.audioOutput.innerHTML = '';
        devices.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.deviceId; opt.text = d.label || d.kind;
            if (d.kind === 'audioinput') dom.audioInput.appendChild(opt);
            else if (d.kind === 'audiooutput') dom.audioOutput.appendChild(opt);
        });
    } catch(e) {}
}

function initSIP() {
    const ext = document.getElementById('sip-ext').value;
    const pwd = document.getElementById('sip-pwd').value;
    if (!ext || !pwd) return;
    
    if (userAgent) userAgent.stop();
    const domain = window.location.hostname;
    
    userAgent = new SIP.UserAgent({
        uri: SIP.UserAgent.makeURI(`sip:${ext}@${domain}`),
        authorizationUsername: ext,
        authorizationPassword: pwd,
        transportOptions: { server: `wss://${domain}/ws` },
        sessionDescriptionHandlerFactoryOptions: {
            peerConnectionOptions: { rtcConfiguration: { sdpSemantics: 'unified-plan' } }
        }
    });
    
    userAgent.transport.onConnect = () => {
        dom.statusPill.style.color = 'var(--go)';
        dom.statusText.innerText = 'Registered';
        dom.uriDisplay.innerText = `sip:${ext}@${domain}`;
        
dom.settingsModal.classList.add('hidden');
    };
    
    // Add logout logic
    const btnLogout = document.getElementById('btn-sip-logout');
    if (btnLogout) {
        btnLogout.onclick = () => {
            localStorage.removeItem('dxt_ext');
            localStorage.removeItem('dxt_pwd');
            if (userAgent) userAgent.stop();
            dom.settingsModal.classList.remove('hidden');
        };
    }

    
    userAgent.transport.onDisconnect = () => {
        dom.statusPill.style.color = 'var(--stop)';
        dom.statusText.innerText = 'Offline';
        const oldAct = activeSession; const oldHeld = heldSession;
        activeSession = null; heldSession = null;
        if(oldAct) cleanupSession(oldAct);
        if(oldHeld) cleanupSession(oldHeld);
        if (incomingSession) { incomingSession = null; dom.incomingModal.classList.add('hidden'); document.getElementById('ringing-audio').pause(); }
        updateStageView();
    };
    
    userAgent.delegate = {
        onInvite: (invitation) => {
            document.getElementById('ringing-audio').play();
            incomingSession = invitation;
            dom.incomingInfo.innerText = invitation.remoteIdentity.displayName || invitation.remoteIdentity.uri.user;
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

document.querySelectorAll('.dial-key').forEach(btn => {
    btn.onclick = () => {
        const num = btn.getAttribute('data-key');
        if (dom.viewDialer.classList.contains('active')) {
            dom.dialInput.value += num;
        } else {
            sendDTMF(num);
        }
    };
});
dom.btnClear.onclick = () => dom.dialInput.value = dom.dialInput.value.slice(0, -1);

dom.btnDial.onclick = () => {
    const target = dom.dialInput.value;
    if (!target) return;
    const uri = SIP.UserAgent.makeURI(`sip:${target}@${window.location.hostname}`);
    const inviter = new SIP.Inviter(userAgent, uri);
    activeSession = inviter;
    bindSessionEvents(activeSession);
    const constraints = dom.audioInput.value ? { audio: { deviceId: { exact: dom.audioInput.value } } } : { audio: true };
    inviter.invite({ sessionDescriptionHandlerOptions: { constraints: constraints } });
    document.getElementById('ringback-audio').play();
    dom.dialInput.value = '';
    updateStageView();
};

dom.btnAccept.onclick = async () => {
    document.getElementById('ringing-audio').pause();
    dom.incomingModal.classList.add('hidden');
    if (activeSession) { await toggleHold(activeSession, true); heldSession = activeSession; }
    activeSession = incomingSession; incomingSession = null;
    bindSessionEvents(activeSession);
    const constraints = dom.audioInput.value ? { audio: { deviceId: { exact: dom.audioInput.value } } } : { audio: true };
    activeSession.accept({ sessionDescriptionHandlerOptions: { constraints: constraints } });
    updateStageView();
};

dom.btnReject.onclick = () => {
    document.getElementById('ringing-audio').pause();
    dom.incomingModal.classList.add('hidden');
    if (incomingSession) { incomingSession.reject(); incomingSession = null; }
};

dom.btnEnd.onclick = () => {
    if (activeSession) {
        if (activeSession.state === SIP.SessionState.Established) activeSession.bye();
        else if (activeSession.state === SIP.SessionState.Establishing) activeSession.cancel();
    }
};

dom.btnIslandEnd.onclick = () => { if (heldSession) heldSession.bye(); };
dom.btnMute.onclick = () => {
    if (!activeSession) return;
    const isMuted = dom.btnMute.classList.contains('active');
    activeSession.sessionDescriptionHandler.peerConnection.getSenders().filter(s => s.track && s.track.kind === 'audio').forEach(s => s.track.enabled = isMuted);
    dom.btnMute.classList.toggle('active');
};
dom.btnHold.onclick = () => toggleHold(activeSession);
dom.btnKeypad.onclick = () => { dom.inCallKeypad.classList.toggle('hidden'); dom.btnKeypad.classList.toggle('active'); };
dom.btnAddCall.onclick = () => { dom.viewCalls.classList.add('hidden'); dom.viewDialer.classList.add('active'); };

function bindSessionEvents(session) {
    session.stateChange.addListener((state) => {
        updateStageView();
        if (state === SIP.SessionState.Established) {
            document.getElementById('ringback-audio').pause();
            const pc = session.sessionDescriptionHandler.peerConnection;
            const rs = new MediaStream();
            pc.getReceivers().forEach(r => { if(r.track) rs.addTrack(r.track); });
            const ae = document.createElement('audio'); ae.autoplay = true; ae.srcObject = rs;
            if(dom.audioOutput.value && typeof ae.setSinkId !== 'undefined') ae.setSinkId(dom.audioOutput.value);
            remoteAudios.set(session, ae);
            if (session === activeSession) startCallTimer();
        }
        if (state === SIP.SessionState.Terminated) {
            document.getElementById('ringback-audio').pause();
            cleanupSession(session);
        }
    });
}

function cleanupSession(session) {
    if (remoteAudios.has(session)) { remoteAudios.get(session).pause(); remoteAudios.get(session).remove(); remoteAudios.delete(session); }
    if (activeSession === session) { activeSession = null; stopCallTimer(); }
    if (heldSession === session) heldSession = null;
    if (!activeSession && heldSession) { activeSession = heldSession; heldSession = null; toggleHold(activeSession, false); }
    updateStageView();
}

async function toggleHold(session, forceHold) {
    if(!session) return;
    const isCurrentlyHeld = dom.btnHold.classList.contains('active');
    const shouldHold = forceHold !== undefined ? forceHold : !isCurrentlyHeld;
    if (shouldHold) {
        dom.btnHold.classList.add('active');
        await session.invite({ sessionDescriptionHandlerModifiers: [(desc) => { desc.sdp = desc.sdp.replace(/a=sendrecv/g, 'a=sendonly'); return Promise.resolve(desc); }]});
    } else {
        dom.btnHold.classList.remove('active');
        await session.invite({ sessionDescriptionHandlerModifiers: [(desc) => { desc.sdp = desc.sdp.replace(/a=sendonly/g, 'a=sendrecv'); return Promise.resolve(desc); }]});
    }
    updateStageView();
}

dom.btnIslandSwap.onclick = async () => {
    const oA = activeSession; const oH = heldSession;
    await toggleHold(oA, true); activeSession = oH; heldSession = oA;
    await toggleHold(activeSession, false); updateStageView();
};

dom.btnIslandMerge.onclick = async () => {
    if(!activeSession || !heldSession) return;
    dom.btnIslandMerge.disabled = true;
    try {
        await heldSession.invite({ sessionDescriptionHandlerModifiers: [(desc) => { desc.sdp = desc.sdp.replace(/a=sendonly/g, 'a=sendrecv'); return Promise.resolve(desc); }]});
        const ac = new (window.AudioContext || window.webkitAudioContext)();
        const s1 = ac.createMediaStreamSource(remoteAudios.get(activeSession).srcObject);
        const s2 = ac.createMediaStreamSource(remoteAudios.get(heldSession).srcObject);
        const ls = await navigator.mediaDevices.getUserMedia(dom.audioInput.value ? { audio: { deviceId: { exact: dom.audioInput.value } } } : { audio: true });
        const sl = ac.createMediaStreamSource(ls);
        const d1 = ac.createMediaStreamDestination(); const d2 = ac.createMediaStreamDestination();
        sl.connect(d1); s2.connect(d1); sl.connect(d2); s1.connect(d2);
        activeSession.sessionDescriptionHandler.peerConnection.getSenders().find(s=>s.track&&s.track.kind==='audio').replaceTrack(d1.stream.getAudioTracks()[0]);
        heldSession.sessionDescriptionHandler.peerConnection.getSenders().find(s=>s.track&&s.track.kind==='audio').replaceTrack(d2.stream.getAudioTracks()[0]);
        dom.btnHold.classList.remove('active');
        dom.activeCallStatus.innerText = "3-Way Conference";
    } catch(e) { alert("Merge failed"); }
    dom.btnIslandMerge.disabled = false;
};

dom.btnTransfer.onclick = () => dom.transferSheet.classList.remove('hidden');
dom.btnCancelTransfer.onclick = () => dom.transferSheet.classList.add('hidden');
dom.btnBlindTransfer.onclick = () => {
    if(!activeSession || !dom.transferTarget.value) return;
    activeSession.refer(SIP.UserAgent.makeURI(`sip:${dom.transferTarget.value}@${window.location.hostname}`));
    dom.transferSheet.classList.add('hidden');
};
dom.btnAttendedTransfer.onclick = () => {
    if(!activeSession || !heldSession) return;
    activeSession.refer(heldSession);
    dom.transferSheet.classList.add('hidden');
};

function sendDTMF(d) {
    if(activeSession) {
        const s = activeSession.sessionDescriptionHandler.peerConnection.getSenders().find(s=>s.track&&s.track.kind==='audio');
        if(s && s.dtmf) s.dtmf.insertDTMF(d);
    }
}

function updateStageView() {
    if (!activeSession && !heldSession) {
        dom.viewCalls.classList.add('hidden'); dom.viewDialer.classList.add('active');
    } else {
        dom.viewDialer.classList.remove('active'); dom.viewCalls.classList.remove('hidden');
        if (activeSession) {
            dom.activeCallerName.innerText = activeSession.remoteIdentity.displayName || activeSession.remoteIdentity.uri.user;
            dom.activeCallStatus.innerText = activeSession.state === SIP.SessionState.Establishing ? "Connecting..." : "Active Call";
        }
        if (heldSession) {
            dom.multiCallIsland.classList.remove('hidden');
            dom.islandHeldName.innerText = heldSession.remoteIdentity.displayName || heldSession.remoteIdentity.uri.user;
        } else {
            dom.multiCallIsland.classList.add('hidden');
        }
    }
}

function startCallTimer() {
    callStartTime = Date.now();
    clearInterval(callTimer);
    callTimer = setInterval(() => {
        const d = Math.floor((Date.now() - callStartTime)/1000);
        dom.activeCallTimer.innerText = String(Math.floor(d/60)).padStart(2,'0')+":"+String(d%60).padStart(2,'0');
    }, 1000);
}
function stopCallTimer() { clearInterval(callTimer); dom.activeCallTimer.innerText = "00:00"; }
