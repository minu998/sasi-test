# SIMPLE BD LIKE API
# POWERED BY : @SIAM_CODEX
from flask import Flask, request, jsonify, send_from_directory
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
import os
import urllib3

urllib3.disable_warnings()

app = Flask(__name__)

# ============================================
# CONFIG
# ============================================
BD_LIKE_URL = "https://clientbp.ggpolarbear.com/LikeProfile"
BD_INFO_URL = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
REGION = "BD"
TOKENS_FILE = "tokens.json"

# ============================================
# LOAD TOKENS FROM tokens.json
# ============================================
def load_tokens():
    """tokens.json එකෙන් JWT tokens load කරනවා
    Supports:
      - [{"token": "..."}, ...]   ← ඔබේ format
      - ["token1", "token2", ...]
      - {"tokens": [...]}
    """
    try:
        # 1. Try environment variable first (Vercel සඳහා)
        env_tokens = os.environ.get("FF_TOKENS")
        if env_tokens:
            try:
                data = json.loads(env_tokens)
                tokens = _extract_tokens(data)
                if tokens:
                    print(f"✅ Loaded {len(tokens)} tokens from ENV")
                    return tokens
            except Exception as e:
                print(f"⚠️ ENV parse error: {e}")
        
        # 2. Fallback to file
        if not os.path.exists(TOKENS_FILE):
            print(f"❌ {TOKENS_FILE} not found!")
            return []
        
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        tokens = _extract_tokens(data)
        print(f"✅ Loaded {len(tokens)} tokens from {TOKENS_FILE}")
        return tokens
    
    except Exception as e:
        print(f"❌ Error loading tokens: {e}")
        return []

def _extract_tokens(data):
    """විවිධ format වලින් tokens extract කරනවා"""
    tokens = []
    
    # Format 1: {"tokens": [...]}
    if isinstance(data, dict) and "tokens" in data:
        data = data["tokens"]
    
    # Format 2: List එකක් නම්
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                # ["token1", "token2"]
                t = item.strip()
                if t:
                    tokens.append(t)
            elif isinstance(item, dict):
                # [{"token": "..."}, ...]  ← ඔබේ format
                t = item.get("token") or item.get("jwt") or item.get("access_token")
                if t and isinstance(t, str):
                    tokens.append(t.strip())
    
    return tokens

# ============================================
# ENCRYPTION
# ============================================
def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(plaintext, AES.block_size)
    return binascii.hexlify(cipher.encrypt(padded)).decode('utf-8')

def enc(uid):
    """UID එක encrypt කරනවා (GetPlayerPersonalShow සඳහා)"""
    msg = uid_generator_pb2.uid_generator()
    msg.krishna_ = int(uid)
    msg.teamXdarks = 1
    return encrypt_message(msg.SerializeToString())

def create_like_message(uid, region):
    """Like protobuf message එක හදනවා"""
    msg = like_pb2.like()
    msg.uid = int(uid)
    msg.region = region
    return msg.SerializeToString()

# ============================================
# DECODE PLAYER INFO
# ============================================
def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except:
        return None

def get_player_info(encrypted_uid, token):
    """Player info ගන්නවා (before/after check සඳහා)"""
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB55"
    }
    try:
        edata = bytes.fromhex(encrypted_uid)
        r = requests.post(BD_INFO_URL, data=edata, headers=headers, verify=False, timeout=10)
        return decode_protobuf(r.content)
    except:
        return None

# ============================================
# SEND ONE LIKE
# ============================================
async def send_like(session, encrypted_uid, token):
    """එක token එකකින් එක like එකක් යවනවා"""
    try:
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        edata = bytes.fromhex(encrypted_uid)
        async with session.post(BD_LIKE_URL, data=edata, headers=headers, timeout=8) as r:
            return r.status
    except:
        return 500

async def send_all_likes(target_uid):
    """හැම token එකකින්ම like යවනවා"""
    tokens = load_tokens()
    if not tokens:
        return {'success': 0, 'failed': 0, 'total': 0}
    
    # Create like message (encrypted)
    protobuf_msg = create_like_message(target_uid, REGION)
    encrypted_uid = encrypt_message(protobuf_msg)
    
    semaphore = asyncio.Semaphore(25)  # 25 concurrent
    
    async def worker(session, token):
        async with semaphore:
            return await send_like(session, encrypted_uid, token)
    
    async with aiohttp.ClientSession() as session:
        tasks = [worker(session, t) for t in tokens]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success = sum(1 for r in results if r == 200)
    failed = len(results) - success
    
    return {'success': success, 'failed': failed, 'total': len(tokens)}

# ============================================
# ROUTES
# ============================================
@app.route("/", methods=["GET"])
def home():
    return send_from_directory(app.root_path, "index.html")

@app.route("/like", methods=["GET"])
def handle_like():
    uid = request.args.get("uid")
    
    if not uid:
        return jsonify({"error": "uid is required", "example": "/like?uid=123456789"}), 400
    
    if not uid.isdigit():
        return jsonify({"error": "uid must be numeric"}), 400
    
    tokens = load_tokens()
    if not tokens:
        return jsonify({"error": "No tokens available in tokens.json"}), 500
    
    encrypted_uid = enc(uid)
    
    # Get a token for checking
    check_token = tokens[0]
    
    # Before likes
    before = get_player_info(encrypted_uid, check_token)
    if before is None:
        return jsonify({"error": "Invalid UID", "status": 0}), 200
    
    try:
        before_data = json.loads(MessageToJson(before))
        before_like = int(before_data['AccountInfo'].get('Likes', 0))
        player_name = str(before_data['AccountInfo'].get('PlayerNickname', 'Unknown'))
        player_uid = int(before_data['AccountInfo'].get('UID', uid))
    except Exception as e:
        return jsonify({"error": f"Parse failed: {str(e)}", "status": 0}), 200
    
    # Send likes (using all tokens)
    result = asyncio.run(send_all_likes(uid))
    
    # After likes
    after = get_player_info(encrypted_uid, check_token)
    if after is None:
        return jsonify({"error": "Could not verify after likes", "status": 0}), 200
    
    try:
        after_data = json.loads(MessageToJson(after))
        after_like = int(after_data['AccountInfo']['Likes'])
        
        like_given = after_like - before_like
        status = 1 if like_given > 0 else 2
        
        return jsonify({
            "LikesGivenByAPI": like_given,
            "LikesafterCommand": after_like,
            "LikesbeforeCommand": before_like,
            "PlayerNickname": player_name,
            "UID": player_uid,
            "TokensUsed": result['total'],
            "TokensSuccess": result['success'],
            "TokensFailed": result['failed'],
            "status": status,
            "credit": "@SIAM_CODEX"
        })
    except Exception as e:
        return jsonify({"error": str(e), "status": 0}), 500

if __name__ == '__main__':
    print("🚀 BD Like API started!")
    print("📁 Token file: tokens.json")
    print("🌐 Example: http://localhost:5001/like?uid=123456789")
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)