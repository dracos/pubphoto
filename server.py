from random import sample
import logging
import time
import socketio
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

# create a Socket.IO server
sio = socketio.Server()

SESSIONS = {}
CHARS = "0123456789ACFHNRUWXY"
SLOTS = {}

for c1 in CHARS:
    for c2 in CHARS:
        for c3 in CHARS:
            for c4 in CHARS:
                if c1 == c2 or c1 == c3 or c1 == c4 or c2 == c3 or c2 == c4 or c3 == c4:
                    # Don't allow slots which are doubles, such as "AA", so that nobody can accidentally press the same letter twice by accident
                    continue
                SLOTS[c1+c2+c3+c4] = {'allocated': False, 'timestamp': 0, 'sender': None, 'receiver': None}

def cleanup():
    now = time.time()
    for k in SLOTS:
        if SLOTS[k]['allocated'] and now - SLOTS[k]['timestamp'] > 60:
            logger.info("Clearing old slot", k);
            SLOTS[k]['allocated'] = False
            SLOTS[k]['socket'] = None

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup, 'interval', minutes=3, id='cleanup', replace_existing=True)
scheduler.start()

@sio.event
def disconnect(sid):
    if sid in SESSIONS:
        SLOTS[SESSIONS[sid]]['allocated'] = False
        del SESSIONS[sid]
        logger.info("Slot", slot, "vanished; freeing it.");

@sio.event
def request_slot(sid):
    keys = sample(SLOTS.keys(), k=len(SLOTS)) 
    for slot in keys:
        if not SLOTS[slot]['allocated']:
            SLOTS[slot]['allocated'] = True
            SLOTS[slot]['timestamp'] = time.time()
            SLOTS[slot]['sender'] = sid
            SLOTS[slot]['receiver'] = None
            SESSIONS[sid] = slot
            break

    if sid in SESSIONS:
        sio.emit('slot_answer', {'slot': slot}, to=sid)
    else:
        logger.info("All slots filled; spinning");
        time.sleep(1)
        request_slot(sid)

@sio.event
def request_from_slot(sid, data):
    if 'slot' not in data: return error(sid, "no_slot", "No slot specified")
    if data['slot'] not in SLOTS: return error(sid, "bad_slot", "Bad slot specified")
    if not SLOTS[data['slot']]['allocated']: return error(sid)

    SLOTS[data['slot']]['receiver'] = sid
    SLOTS[data['slot']]['timestamp'] = time.time()
    sio.emit("transmit_now", to=SLOTS[data['slot']]['sender'])
    SESSIONS[sid] = data['slot']

@sio.event
def transmission(sid, data):
    slot = SESSIONS[sid]
    if not SLOTS[slot]['allocated']: return error(sid)
    if not SLOTS[slot]['receiver']: return error(sid)
    # retransmit the data to the receiver
    sio.emit("transmission", data, to=SLOTS[slot]['receiver'])
    # and bump the timestamp so we don't garbage collect it mid-transmission
    SLOTS[slot]['timestamp'] = time.time()

@sio.event
def got_all(sid):
    # receiver has received everything; tear it all down
    slot = SESSIONS[sid]
    sio.emit("got_all", to=SLOTS[slot]['sender'])
    SLOTS[slot]['allocated'] = False
    del SESSIONS[sid]
    logger.info("Slot", slot, "finished with; freeing it.");

def error(sid, code="old_slot", text="That code has run out. Ask them to send the image again."):
    sio.emit("servererror", {'code': code, 'text': text}, to=sid)

application = socketio.WSGIApp(sio, socketio_path='/')
