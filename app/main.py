from flask import Flask
from flask import request, render_template, redirect, url_for, session, make_response

import os
from functools import wraps
import base58
import threading
import redis
import json

app = Flask(__name__)
app.secret_key = open("/run/secrets/rps_secret_key","rb").read()

r = redis.StrictRedis(host='redis', port=6379, db=0)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'uid' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
    
def room_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        rid = kwargs['rid']
        try:
            rid = base58.b58decode_check(rid)
            rid = int.from_bytes(rid, "big")
        except:
            return 'Arg error'
        if not r.exists(rid):
            return 'Room not exist'
        return f(rid)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session['username'] = request.form['username']
        session['uid'] = int.from_bytes(os.urandom(12),'big')
        return redirect('/')
    return '<form action="" method="post">username: <input name="username">'

@app.route('/', methods=['GET'])
@login_required
def index():
    return '<p>Iric\'s Rock Paper Scissors</p><a href="' + url_for('create') + '"> Create room </a><p><a href="' + url_for('logout') + '"> Logout </p>'

def room_getplayer(uid, rid):
    for i in range(r.llen(rid)):
        rpid = r.lindex(rid,i)
        if int(r.hmget(rpid,'uid')[0]) == uid:
            return rpid
    return None
    
def room_addplayer(uid, rid):
    rpid = int(str(rid)+str(session['uid']))
    rp = {'uid': session['uid'], 'username': session['username'], 'msg': json.dumps([''])}
    r.hmset(rpid, rp)
    r.rpush(rid, rpid)

@app.route('/create', methods=['GET'])
@login_required
def create():
    rid = int.from_bytes(os.urandom(8), "big")
    room_addplayer(session['uid'], rid)
    return redirect(url_for('play', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()))

@app.route('/play/<rid>', methods=['GET', 'POST'])
@login_required
@room_required
def play(rid):
    link = url_for('play', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode())
    u = room_getplayer(session['uid'], rid)
    if not u:
        room_addplayer(session['uid'], rid)
        return redirect(link)
    s = '<p><a href="' + link + '"> Share this link to your partner </a></p>'
    ready = True
    for x in r.lrange(rid,0,-1):
        if json.loads(r.hmget(x, 'msg')[0])[-1] == '':
            ready = False
            break
    if ready:
        for x in r.lrange(rid,0,-1):
            r.hset(x, key='msg', value=json.dumps(json.loads(r.hmget(x, 'msg')[0])+['']))
    if request.method == 'POST':
        msg = json.loads(r.hmget(u, 'msg')[0])
        msg[-1] = request.form['msg']
        r.hset(u, key='msg', value=json.dumps(msg))
        return redirect(url_for('play', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()))

    l = len(json.loads(r.hmget(r.lindex(rid,0), 'msg')[0]))
    for x in r.lrange(rid,0,-1):
        if len(json.loads(r.hmget(x, 'msg')[0])) < l:
            l = len(json.loads(r.hmget(x, 'msg')[0]))

    for i in range(l):
        s += f"<p> Round {i}: "
        for x in r.lrange(rid,0,-1):
            s += f"{r.hmget(x, 'username')[0].decode()}: "
            if int(r.hmget(x, 'uid')[0]) == session['uid'] or i < l-1:
                s += json.loads(r.hmget(x, 'msg')[0])[i] # TODO: render safely
            s += '\t'
        s += "</p>"
    return s + '<form action="" method="post">msg: <input name="msg">' + '<p><a href="' + url_for('leave', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()) + '"> leave room </a></p>'

@app.route('/leave/<rid>', methods=['GET'])
@login_required
@room_required
def leave(rid):
    u = room_getplayer(session['uid'], rid)
    if not u:
        return 'You are not in that room'
    r.delete(u)
    r.lrem(rid,0,u)
    return redirect('/')

@app.route('/logout', methods=['GET'])
@login_required
def logout():
    del session['uid']
    del session['username']
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=10008, debug=True)