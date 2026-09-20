
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
    btnShowSettings: document.getElementById('btn-show-settings'),
    btnSaveSettings: document.getElementById('btn-save-settings'),
    btnCloseSettings: document.getElementById('btn-close-settings'),
    
    incomingModal: document.getElementById('incoming-modal'),
    incomingInfo: document.getElementById('incoming-caller-info'),
    btnAccept: document.getElementById('btn-incoming-accept'),
    btnReject: document.getElementById('btn-incoming-reject'),
    
    activeCallStage: document.getElementById('active-call-stage'),
    activeCallerName: document.getElementById('active-caller-name'),
    activeCallStatus: document.getElementById('active-call-status'),
    activeCallTimer: document.getElementById('active-call-timer'),
    
    btnMute: document.getElementById('btn-ctrl-mute'),
    btnKeypad: document.getElementById('btn-ctrl-keypad'),
    btnHold: document.getElementById('btn-ctrl-hold'),
    btnTransfer: document.getElementById('btn-ctrl-transfer'),
    btnEnd: document.getElementById('btn-ctrl-end'),
    
    multiCallIsland: document.getElementById('multi-call-island'),
    islandHeldName: document.getElementById('island-held-name'),
    btnIslandSwap: document.getElementById('btn-island-swap'),
    btnIslandMerge: document.getElementById('btn-island-merge'),
    btnIslandTransfer: document.getElementById('btn-island-transfer'),
    btnIslandEnd: document.getElementById('btn-island-end'),
    
    transferSheet: document.getElementById('transfer-sheet'),
    transferTarget: document.getElementById('transfer-target'),
    btnBlindTransfer: document.getElementById('btn-blind-transfer'),
    btnAttendedTransfer: document.getElementById('btn-attended-transfer'),
    btnCancelTransfer: document.getElementById('btn-cancel-transfer'),
    
    audioInput: document.getElementById('audio-input-select'),
    audioOutput: document.getElementById('audio-output-select'),
    blfList: document.getElementById('blf-list'),
    blfSearch: document.getElementById('blf-search')
};

let userAgent = null;
let activeSession = null;
let heldSession = null;
let incomingSession = null;
let activeCallTimerId = null;
let activeCallSeconds = 0;
let mediaStreams = new Map(); // session -> MediaStream
let remoteAudios = new Map(); // session -> HTMLAudioElement

// Theme Toggle
dom.themeBtn.onclick = () => {
    const isLight = document.body.getAttribute('data-theme') === 'light';
    document.body.setAttribute('data-theme', isLight ? 'dark' : 'light');
    dom.themeBtn.innerHTML = isLight ? '<i class="fa-solid fa-moon"></i>' : '<i class="fa-solid fa-sun"></i>';
};

// Dialpad Logic
document.querySelectorAll('.keypad-btn').forEach(btn => {
    btn.onclick = () => {
        const key = btn.getAttribute('data-key');
        dom.dialInput.value += key;
        if (activeSession) {
            playDTMF(key);
            sendDTMF(activeSession, key);
        }
    };
});
dom.btnClear.onclick = () => { dom.dialInput.value = dom.dialInput.value.slice(0, -1); };

// Hardware Audio Enumeration & Hot-Swapping
async function enumerateDevices() { if (!navigator.mediaDevices) return;
    try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        dom.audioInput.innerHTML = '';
        dom.audioOutput.innerHTML = '';
        devices.forEach(device => {
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.text = device.label || `Device ${device.deviceId.substring(0, 5)}`;
            if (device.kind === 'audioinput') dom.audioInput.appendChild(option);
            if (device.kind === 'audiooutput') dom.audioOutput.appendChild(option);
        });
    } catch (err) {
        console.error('Failed to enumerate devices', err);
    }
}
if(navigator.mediaDevices) { navigator.mediaDevices.ondevicechange = enumerateDevices; } else { alert("WebRTC requires HTTPS! Please access this page using https:// to enable microphone and calling."); console.warn("mediaDevices API not available."); }
dom.audioInput.onchange = applyAudioDevices;
dom.audioOutput.onchange = applyAudioDevices;

async function applyAudioDevices() {
    const inputId = dom.audioInput.value;
    const outputId = dom.audioOutput.value;
    
    // Output
    if (outputId) {
        remoteAudios.forEach(audio => {
            if (audio.setSinkId) audio.setSinkId(outputId);
        });
        const ringback = document.getElementById('ringback-audio');
        const ringing = document.getElementById('ringing-audio');
        if (ringback.setSinkId) ringback.setSinkId(outputId);
        if (ringing.setSinkId) ringing.setSinkId(outputId);
    }
    
    // Input (Hot-swap for active calls)
    if (inputId && activeSession) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: { exact: inputId } } });
            const track = stream.getAudioTracks()[0];
            const sender = activeSession.sessionDescriptionHandler.peerConnection.getSenders().find(s => s.track && s.track.kind === 'audio');
            if (sender) {
                await sender.replaceTrack(track);
                console.log('Successfully hot-swapped microphone track!');
            }
        } catch(e) { console.error('Hot-swap failed', e); }
    }
}
enumerateDevices();

// BLF Logic
function updateBLF() {
    fetch('/api/extensions_live_status')
        .then(r => r.json())
        .then(data => {
            const term = dom.blfSearch.value.toLowerCase();
            dom.blfList.innerHTML = '';
            data.forEach(ext => {
                if (ext.ext === document.getElementById('sip-ext').value) return; // skip self
                if (term && !ext.ext.includes(term) && !ext.name.toLowerCase().includes(term)) return;
                
                const btn = document.createElement('div');
                btn.className = 'blf-item';
                btn.innerHTML = `
                    <div class="blf-info">
                        <div class="blf-dot ${ext.status}"></div>
                        <div>
                            <div style="font-size:13px;">${ext.name}</div>
                            <div style="font-size:10px; color:var(--text2);">${ext.ext}</div>
                        </div>
                    </div>
                    <button class="icon-btn" onclick="dialNumber('${ext.ext}')"><i class="fa-solid fa-phone"></i></button>
                `;
                dom.blfList.appendChild(btn);
            });
        }).catch(e => console.error(e));
}
setInterval(updateBLF, 5000);
dom.blfSearch.onkeyup = updateBLF;
updateBLF();

// Helper to dial a number
window.dialNumber = function(num) {
    if (activeSession) return; // Block if in call
    dom.dialInput.value = num;
    dom.btnDial.click();
};

// SIP Initialization & Settings
dom.btnShowSettings.onclick = () => { dom.settingsModal.classList.remove('hidden'); };
dom.btnCloseSettings.onclick = () => { dom.settingsModal.classList.add('hidden'); };
dom.btnSaveSettings.onclick = () => {
    localStorage.setItem('dexter_ext', dom.settingsModal.querySelector('#sip-ext').value);
    localStorage.setItem('dexter_pwd', dom.settingsModal.querySelector('#sip-pwd').value);
    dom.settingsModal.classList.add('hidden');
    initSIP();
};
document.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('dexter_ext')) {
        dom.settingsModal.querySelector('#sip-ext').value = localStorage.getItem('dexter_ext');
        dom.settingsModal.querySelector('#sip-pwd').value = localStorage.getItem('dexter_pwd');
        initSIP();
    } else {
        dom.settingsModal.classList.remove('hidden');
    }
});

function initSIP() {
    if (userAgent) userAgent.stop();
    
    const ext = dom.settingsModal.querySelector('#sip-ext').value;
    const pwd = dom.settingsModal.querySelector('#sip-pwd').value;
    const domain = window.location.hostname;
    
    dom.uriDisplay.innerText = `Ext. ${ext}`;
    dom.statusPill.className = 'status-pill';
    dom.statusText.innerText = 'Connecting...';
    
    const uri = SIP.UserAgent.makeURI(`sip:${ext}_webrtc@${domain}`);
    userAgent = new SIP.UserAgent({
        uri: uri,
        transportOptions: { server: `wss://${domain}/ws` },
        authorizationUsername: `${ext}_webrtc`,
        authorizationPassword: pwd,
        delegate: {
            onInvite: handleInvite
        }
    });
    
    const registerer = new SIP.Registerer(userAgent);
    
    userAgent.start().then(() => registerer.register())
    .then(() => {
        dom.statusPill.className = 'status-pill registered';
        dom.statusText.innerText = 'Registered ✔';
    })
    .catch(err => {
        dom.statusPill.className = 'status-pill offline';
        dom.statusText.innerText = 'Offline ✖';
        console.error(err);
    });
}

function updateStageView() {
    if (activeSession || heldSession) {
        dom.viewDialer.classList.remove('active');
        dom.viewCalls.classList.add('active');
        
        if (activeSession) {
            dom.activeCallerName.innerText = activeSession.remoteIdentity.displayName || activeSession.remoteIdentity.uri.user;
            const state = activeSession.state;
            if (state === SIP.SessionState.Establishing) dom.activeCallStatus.innerText = 'Ringing...';
            else if (state === SIP.SessionState.Established) {
                if (dom.btnHold.classList.contains('active')) {
                    dom.activeCallStatus.innerText = 'Held (by you)';
                    dom.activeCallStatus.style.color = 'var(--wait)';
                } else {
                    dom.activeCallStatus.innerText = 'Connected';
                    dom.activeCallStatus.style.color = 'var(--go)';
                }
            }
        }
        
        if (heldSession) {
            dom.multiCallIsland.classList.remove('hidden');
            dom.islandHeldName.innerText = heldSession.remoteIdentity.displayName || heldSession.remoteIdentity.uri.user;
        } else {
            dom.multiCallIsland.classList.add('hidden');
        }
        
    } else {
        dom.viewCalls.classList.remove('active');
        dom.viewDialer.classList.add('active');
        stopCallTimer();
    }
}

// Timer Logic
function startCallTimer() {
    if (activeCallTimerId) return;
    activeCallSeconds = 0;
    activeCallTimerId = setInterval(() => {
        activeCallSeconds++;
        const m = String(Math.floor(activeCallSeconds/60)).padStart(2,'0');
        const s = String(activeCallSeconds%60).padStart(2,'0');
        dom.activeCallTimer.innerText = `${m}:${s}`;
    }, 1000);
}
function stopCallTimer() {
    clearInterval(activeCallTimerId);
    activeCallTimerId = null;
    dom.activeCallTimer.innerText = '00:00';
}

function getAudioElement(session) {
    if (!remoteAudios.has(session)) {
        const audio = new Audio();
        audio.autoplay = true;
        document.body.appendChild(audio);
        remoteAudios.set(session, audio);
        if (dom.audioOutput.value && audio.setSinkId) audio.setSinkId(dom.audioOutput.value);
    }
    return remoteAudios.get(session);
}
function cleanupSession(session) {
    if (remoteAudios.has(session)) {
        const a = remoteAudios.get(session);
        a.pause();
        a.remove();
        remoteAudios.delete(session);
    }
    if (activeSession === session) activeSession = null;
    if (heldSession === session) heldSession = null;
    
    // Auto-unhold logic
    if (!activeSession && heldSession) {
        activeSession = heldSession;
        heldSession = null;
        toggleHold(activeSession, false); // Resume
    }
    updateStageView();
}

function bindSessionEvents(session) {
    session.stateChange.addListener((state) => {
        updateStageView();
        if (state === SIP.SessionState.Established) {
            document.getElementById('ringback-audio').pause();
            document.getElementById('ringing-audio').pause();
            startCallTimer();
        const pc = session.sessionDescriptionHandler.peerConnection;
        const remoteStream = new MediaStream();
        pc.getReceivers().forEach(r => { if(r.track) remoteStream.addTrack(r.track); });
        getAudioElement(session).srcObject = remoteStream;
        }
        if (state === SIP.SessionState.Terminated) {
            document.getElementById('ringback-audio').pause();
            document.getElementById('ringing-audio').pause();
            cleanupSession(session);
        }
    });
}

// Making a Call
dom.btnDial.onclick = async () => {
    const target = dom.dialInput.value;
    if (!target) return;
    
    if (activeSession) {
        // We have an active call, put it on hold first!
        await toggleHold(activeSession, true);
        heldSession = activeSession;
        activeSession = null;
    }
    
    const uri = SIP.UserAgent.makeURI(`sip:${target}@${window.location.hostname}`);
    
    const inputId = dom.audioInput.value;
    const constraints = inputId ? { audio: { deviceId: { exact: inputId } } } : { audio: true };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    
    const inviter = new SIP.Inviter(userAgent, uri, {
        sessionDescriptionHandlerOptions: { constraints: constraints }
    });
    activeSession = inviter;
    bindSessionEvents(inviter);
    inviter.invite();
    document.getElementById('ringback-audio').play();
    updateStageView();
};

// Receiving a Call
function handleInvite(invitation) {
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

dom.btnAccept.onclick = async () => {
    document.getElementById('ringing-audio').pause();
    dom.incomingModal.classList.add('hidden');
    
    if (activeSession) {
        await toggleHold(activeSession, true);
        heldSession = activeSession;
    }
    
    const inputId = dom.audioInput.value;
    const constraints = inputId ? { audio: { deviceId: { exact: inputId } } } : { audio: true };
    
    activeSession = incomingSession;
    bindSessionEvents(activeSession);
    activeSession.accept({
        sessionDescriptionHandlerOptions: { constraints: constraints }
    });
};

dom.btnReject.onclick = () => {
    document.getElementById('ringing-audio').pause();
    dom.incomingModal.classList.add('hidden');
    if (incomingSession) {
        incomingSession.reject();
        incomingSession = null;
    }
};

// In-Call Controls
dom.btnEnd.onclick = () => {
    if (activeSession) {
        if (activeSession.state === SIP.SessionState.Established) activeSession.bye();
        else if (activeSession.state === SIP.SessionState.Establishing) activeSession.cancel();
    }
};
dom.btnIslandEnd.onclick = () => {
    if (heldSession) heldSession.bye();
};

dom.btnMute.onclick = () => {
    if (!activeSession) return;
    const pc = activeSession.sessionDescriptionHandler.peerConnection;
    const senders = pc.getSenders().filter(s => s.track && s.track.kind === 'audio');
    const isMuted = dom.btnMute.classList.contains('active');
    senders.forEach(s => s.track.enabled = isMuted); // Flip
    dom.btnMute.classList.toggle('active');
};

async function toggleHold(session, forceHold) {
    if (!session) return;
    const isCurrentlyHeld = dom.btnHold.classList.contains('active');
    const shouldHold = forceHold !== undefined ? forceHold : !isCurrentlyHeld;
    
    if (shouldHold) {
        dom.btnHold.classList.add('active');
        await session.invite({
            sessionDescriptionHandlerModifiers: [
                (sdp) => sdp.replace(/a=sendrecv/g, 'a=sendonly')
            ]
        });
    } else {
        dom.btnHold.classList.remove('active');
        await session.invite({
            sessionDescriptionHandlerModifiers: [
                (sdp) => sdp.replace(/a=sendonly/g, 'a=sendrecv')
            ]
        });
    }
    updateStageView();
}
dom.btnHold.onclick = () => toggleHold(activeSession);

dom.btnIslandSwap.onclick = async () => {
    const oldActive = activeSession;
    const oldHeld = heldSession;
    
    // Put current on hold
    await toggleHold(oldActive, true);
    
    // Make held active
    activeSession = oldHeld;
    heldSession = oldActive;
    
    // Resume new active
    await toggleHold(activeSession, false);
    updateStageView();
};

dom.btnIslandMerge.onclick = () => {
    alert('3-Way Conference via WebRTC Mix-Minus requires AudioContext processing which is not implemented in this demo. Ask the engineer to write the Audio Bridge!');
};

dom.btnTransfer.onclick = () => { dom.transferSheet.classList.remove('hidden'); };
dom.btnCancelTransfer.onclick = () => { dom.transferSheet.classList.add('hidden'); };

dom.btnBlindTransfer.onclick = () => {
    const target = dom.transferTarget.value;
    if (!target || !activeSession) return;
    const uri = SIP.UserAgent.makeURI(`sip:${target}@${window.location.hostname}`);
    activeSession.refer(uri);
    dom.transferSheet.classList.add('hidden');
};

dom.btnAttendedTransfer.onclick = () => {
    if (!heldSession || !activeSession) {
        alert("You must have a held call to perform attended transfer.");
        return;
    }
    activeSession.refer(heldSession);
    dom.transferSheet.classList.add('hidden');
};

function playDTMF(digit) {
    // Optional client side beep
}
function sendDTMF(session, digit) {
    const pc = session.sessionDescriptionHandler.peerConnection;
    const senders = pc.getSenders();
    const audioSender = senders.find(s => s.track && s.track.kind === 'audio');
    if (audioSender && audioSender.dtmf) {
        audioSender.dtmf.insertDTMF(digit);
    }
}
dom.btnKeypad.onclick = () => {
    // Toggles between keypad overlay
    dom.viewDialer.classList.add('active');
    dom.viewCalls.classList.remove('active');
    // Hide dial input, just show keypad
    dom.dialInput.style.display = 'none';
};
