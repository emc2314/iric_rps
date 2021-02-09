from flask import Flask
from flask import request, render_template, redirect, url_for, session, make_response

import os
from functools import wraps
import base58
import redis
import json

app = Flask(__name__)
if __name__ == '__main__':
    app.secret_key = b"hyhvjhg546c"
    r = redis.StrictRedis(host='localhost', port=6379, db=0)
else:
    app.secret_key = open("/run/secrets/rps_secret_key","rb").read()
    r = redis.StrictRedis(host='redis', port=6379, db=0)

class RoomPlayer:
    def __init__(self, rpid, rid):
        self.rpid = rpid
        self.rid = rid
        assert rpid.startswith(str(rid))

    @classmethod
    def from_uid(cls, uid, rid):
        rpid = str(rid) + '/' + str(uid)
        r.hset(rpid, key='uid', value=uid)
        return cls(rpid, rid)

    @property
    def actions(self):
        return json.loads(r.hmget(self.rpid, 'actions')[0])

    @actions.setter
    def actions(self, actions):
        r.hset(self.rpid, key='actions', value=json.dumps(actions))

    def __getitem__(self, key):
        return r.hmget(self.rpid, key)[0]

    def __setitem__(self, key, value):
        r.hset(self.rpid, key=key, value=value)


class Room:
    def __init__(self, rid):
        self.rid = rid
        if not r.exists(rid):
            raise Exception("Room not found")

    @classmethod
    def create(cls, rid):
        player = RoomPlayer.from_uid(0, rid)
        r.rpush(rid, player.rpid)
        return cls(rid)

    def __len__(self):
        return r.llen(self.rid)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return map(self.__getitem__, range(i.start or 0, i.stop if i.stop else len(self), i.step or 1))
        else:
            if i >= len(self):
                raise IndexError
            return RoomPlayer(r.lindex(self.rid,i).decode(), self.rid)

    def get_player(self, uid):
        for player in self:
            if int(player['uid']) == uid:
                return player
        return None

    def new_player(self, uid, username):
        player = RoomPlayer.from_uid(uid, self.rid)
        player['username'] = username
        player.actions = ['']
        r.rpush(self.rid, player.rpid)

    def remove_player(self, player):
        r.delete(player.rpid)
        r.lrem(self.rid,0,player.rpid)
        if len(self) == 1:
            r.delete(self[0].rpid)
            r.lrem(self.rid,0,self[0].rpid)


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
            room = Room(rid)
        except ValueError:
            return 'Arg error'
        except:
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

@app.route('/create', methods=['GET'])
@login_required
def create():
    rid = int.from_bytes(os.urandom(8), "big")
    room = Room.create(rid)
    return redirect(url_for('play', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()))

@app.route('/play/<rid>', methods=['GET', 'POST'])
@login_required
@room_required
def play(rid):
    linkid = base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()
    room = Room(rid)
    player = room.get_player(session['uid'])
    if not player:
        room.new_player(session['uid'], session['username'])
        return redirect(url_for('play', rid=linkid))
    ready = True
    for x in room[1:]:
        if x.actions[-1] == '':
            ready = False
            break
    if ready:
        for x in room[1:]:
            x.actions += ['']
    if request.method == 'POST':
        actions = player.actions
        actions[-1] = request.form['actions']
        player.actions = actions
        return redirect(url_for('play', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()))

    l = len(room[1].actions)
    for x in room[1:]:
        if len(x.actions) < l:
            l = len(x.actions)
    s = ''
    for i in range(l,0,-1):
        s += f"<p> Round {l-i}: "
        for x in room[1:]:
            s += f"{x['username'].decode()}: "
            if int(x['uid']) == session['uid'] or i > 1:
                s += x.actions[-i] # TODO: render safely
            s += '\t'
        s += "</p>"
    return s + '<form action="" method="post">actions: <input name="actions">' + '<p><a href="' + url_for('leave', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()) + '"> leave room </a></p>'
    #return render_template('play.html', linkid=linkid, )

@app.route('/leave/<rid>', methods=['GET'])
@login_required
@room_required
def leave(rid):
    room = Room(rid)
    player = room.get_player(session['uid'])
    room.remove_player(player)
    return redirect('/')

@app.route('/logout', methods=['GET'])
@login_required
def logout():
    del session['uid']
    del session['username']
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=10008, debug=True)