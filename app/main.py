from flask import Flask
from flask import request, render_template, redirect, url_for, session, make_response

import os
from functools import wraps
import base58
import redis
import json
import random

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
        player.actions = [{'skill':'','roll':''}]
        r.rpush(self.rid, player.rpid)
        return player

    def remove_player(self, player):
        r.delete(player.rpid)
        r.lrem(self.rid,0,player.rpid)
        if len(self) == 1:
            r.delete(self[0].rpid)
            r.delete(self.rid)

class Skill:
    def __init__(self, sk):
        self.id = sk['num']
        self.name = sk['name']
        self.type = sk['target']
        self.dices = sk['random']

    def __repr__(self):
        j = {}
        j['num'] = self.id
        j['name'] = self.name
        j['target'] = self.type
        j['random'] = self.dices
        return json.dumps(j)

    def roll(self):
        result = []
        for d in self.dices:
            a, b = d.split('d')
            x = 0
            for i in range(int(a)):
                x += random.randint(1,int(b))
            result.append(x)
        return result

class Character:
    def __init__(self, char, skdict):
        self.id = char['num']
        self.name = char['name']
        self.skills = []
        for x in char['skill']:
            self.skills.append(skdict[x])

    def __repr__(self):
        j = {}
        j['num'] = self.id
        j['name'] = self.name
        j['skill'] = [repr(x) for x in self.skills]
        return json.dumps(j)

def parse_charsk(charl, skl):
    charl = json.loads(charl)
    skl = json.loads(skl)
    skdict = {}
    for sk in skl:
        sk = Skill(sk)
        skdict[sk.id] = sk
    chardict = {}
    for character in charl:
        character = Character(character, skdict)
        chardict[character.id] = character
    return chardict, skdict


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
    return render_template('index.html')

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        skl = request.form['skill_list'].strip()
        charl = request.form['character_list'].strip()
        try:
            parse_charsk(charl, skl)
        except:
            return "Error load rule lists"
        r.set('skills', skl)
        r.set('characters', charl)
    else:
        skl = r.get('skills')
        charl = r.get('characters')
        if not (skl and charl):
            return 'Set default rules first'
    rid = int.from_bytes(os.urandom(8), "big")
    room = Room.create(rid)
    room[0]['skills'] = skl
    room[0]['characters'] = charl
    return redirect(url_for('join', rid=base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()))


@app.route('/join/<rid>', methods=['GET', 'POST'])
@login_required
@room_required
def join(rid):
    linkid = base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()
    room = Room(rid)
    player = room.get_player(session['uid'])
    if player:
        return redirect(url_for('play', rid=linkid))
    chardict, skdict = parse_charsk(room[0]['characters'], room[0]['skills'])
    if request.method == 'GET':
        return render_template('join.html', chardict=chardict)
    else:
        character = request.form['character']
        if character not in chardict:
            return 'Character not found\n' + str(chardict) + '\n' + str(skdict)
        player = room.new_player(session['uid'], session['username'])
        player['character'] = character


    return redirect(url_for('play', rid=linkid))

@app.route('/logs/<rid>', methods=['GET'])
@login_required
@room_required
def logs(rid):
    linkid = base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()
    room = Room(rid)
    player = room.get_player(session['uid'])
    if not player:
        return redirect(url_for('join', rid=linkid))

    rounds = len(room[1].actions)
    for x in room[1:]:
        if len(x.actions) < rounds:
            rounds = len(x.actions)
    chardict, skdict = parse_charsk(room[0]['characters'], room[0]['skills'])
    logs = []
    for i in range(rounds,0,-1):
        s = {}
        for x in room[1:]:
            if x.actions[-i]['skill'] != '':
                if int(x['uid']) == session['uid'] or i > 1:
                    action = x.actions[-i]
                    s[x.rpid] = skdict[action['skill']].name + action['roll']
                else:
                    s[x.rpid] = 'READY'
            else:
                s[x.rpid] = ''
        logs.append(s)

    uid = ''
    if rounds >= 2:
        if player.actions[-2]['roll'] == '':
            if len(skdict[player.actions[-2]['skill']].dices):
                uid = str(session['uid']).encode()

    return render_template('logs.html', linkid=linkid, chardict=chardict, players=list(room[1:]), rounds=rounds, logs=logs, uid=uid)

@app.route('/roll/<rid>', methods=['GET'])
@login_required
@room_required
def roll(rid):
    linkid = base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()
    room = Room(rid)
    player = room.get_player(session['uid'])
    if not player:
        return redirect(url_for('join', rid=linkid))

    rounds = len(room[1].actions)
    for x in room[1:]:
        if len(x.actions) < rounds:
            rounds = len(x.actions)
    if rounds < 2:
        return "Nothing to roll"
    chardict, skdict = parse_charsk(room[0]['characters'], room[0]['skills'])
    for x in room[1:]:
        if int(x['uid']) == session['uid']:
            skill = skdict[x.actions[-2]['skill']]
            actions = x.actions
            if actions[-2]['roll'] == '':
                actions[-2]['roll'] = " [" + ", ".join(map(lambda x: str(x[0])+'/'+x[1], zip(skill.roll(), skill.dices))) + "]"
                x.actions = actions
            break

    return ''


@app.route('/play/<rid>', methods=['GET', 'POST'])
@login_required
@room_required
def play(rid):
    linkid = base58.b58encode_check(int.to_bytes(rid,8,"big")).decode()
    room = Room(rid)
    player = room.get_player(session['uid'])
    if not player:
        return redirect(url_for('join', rid=linkid))

    if request.method == 'POST':
        actions = player.actions
        actions[-1] = {'skill': request.form['action'], 'roll':''}
        player.actions = actions
        ready = True
        for x in room[1:]:
            if x.actions[-1]['skill'] == '':
                ready = False
                break
        if ready:
            for x in room[1:]:
                x.actions += [{'skill':'','roll':''}]
        return ''

    chardict, skdict = parse_charsk(room[0]['characters'], room[0]['skills'])
    return render_template('play.html', linkid=linkid, chardict=chardict, player=player)

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