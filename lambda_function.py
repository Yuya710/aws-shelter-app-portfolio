import json
import boto3
from decimal import Decimal
from datetime import datetime
import logging

# ロガーの設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table('shelterDB')
supplies_table = dynamodb.Table('ShelterSupplies')
requests_table = dynamodb.Table('SupplyRequests')
warehouse_table = dynamodb.Table('WarehouseInventory')
users_table = dynamodb.Table('ShelterUsers')
bedrock = boto3.client('bedrock-runtime', region_name='ap-northeast-1')

class ValidationError(Exception):
    """入力検証エラー"""
    pass

def validate_supply_input(data):
    """
    物資情報の入力を検証する
    
    Args:
        data: 検証するデータ（辞書）
    
    Returns:
        tuple: (is_valid, error_message)
    
    Raises:
        ValidationError: 検証エラーの場合
    """
    if not data.get('shelter_id') or data.get('shelter_id', '').strip() == '':
        raise ValidationError('避難所IDは必須です')
    
    if not data.get('item_name') or data.get('item_name', '').strip() == '':
        raise ValidationError('物資品目は必須です')
    
    if 'quantity' not in data:
        raise ValidationError('数量は必須です')
    
    try:
        quantity = int(data['quantity'])
        if quantity < 0:
            raise ValidationError('数量は0以上である必要があります')
        if quantity > 100000:
            raise ValidationError('数量は100,000以下である必要があります（入力値: {})'.format(quantity))
    except (ValueError, TypeError):
        raise ValidationError('数量は数値である必要があります')
    
    return True

def check_shelter_exists(shelter_id):
    """
    避難所が存在するか確認する
    
    Args:
        shelter_id: 避難所ID
    
    Returns:
        bool: 存在する場合True
    """
    try:
        response = table.get_item(
            Key={'shelterID': shelter_id}
        )
        return 'Item' in response
    except Exception as e:
        logger.warning(f"Error checking shelter existence: {str(e)}")
        return False

def register_supply(shelter_id, item_name, quantity):
    """
    物資情報を登録・更新する
    
    Args:
        shelter_id: 避難所ID
        item_name: 物資品目
        quantity: 数量
    
    Returns:
        dict: 登録された物資情報
    """
    updated_at = datetime.utcnow().isoformat() + 'Z'
    
    supplies_table.put_item(
        Item={
            'shelter_id': shelter_id,
            'item_name': item_name,
            'quantity': Decimal(str(quantity)),
            'updated_at': updated_at
        }
    )
    
    return {
        'shelter_id': shelter_id,
        'item_name': item_name,
        'quantity': quantity,
        'updated_at': updated_at
    }

def get_supplies_by_shelter(shelter_id):
    """
    特定の避難所の物資情報を取得する
    
    Args:
        shelter_id: 避難所ID
    
    Returns:
        dict: 避難所の物資情報
    """
    if not shelter_id or shelter_id.strip() == '':
        raise ValidationError('避難所IDは必須です')
    
    response = supplies_table.query(
        KeyConditionExpression='shelter_id = :sid',
        ExpressionAttributeValues={
            ':sid': shelter_id
        }
    )
    
    supplies = []
    for item in response.get('Items', []):
        supplies.append({
            'item_name': item.get('item_name', ''),
            'quantity': float(item.get('quantity', 0)),
            'updated_at': item.get('updated_at', '')
        })
    
    return {
        'shelter_id': shelter_id,
        'supplies': supplies
    }

def get_all_supplies():
    """
    全避難所の物資情報を取得する
    
    Returns:
        dict: 全避難所の物資情報（避難所IDごとにグループ化）
    """
    response = supplies_table.scan()
    
    # 避難所IDごとにグループ化
    shelters_dict = {}
    for item in response.get('Items', []):
        shelter_id = item.get('shelter_id', '')
        if shelter_id not in shelters_dict:
            shelters_dict[shelter_id] = []
        
        shelters_dict[shelter_id].append({
            'item_name': item.get('item_name', ''),
            'quantity': float(item.get('quantity', 0)),
            'updated_at': item.get('updated_at', '')
        })
    
    # リスト形式に変換
    shelters = []
    for shelter_id, supplies in shelters_dict.items():
        shelters.append({
            'shelter_id': shelter_id,
            'supplies': supplies
        })
    
    return {'shelters': shelters}

def delete_supply(shelter_id, item_name):
    """
    物資情報を削除する
    
    Args:
        shelter_id: 避難所ID
        item_name: 物資品目
    
    Returns:
        dict: 削除結果
    """
    if not shelter_id or shelter_id.strip() == '':
        raise ValidationError('避難所IDは必須です')
    
    if not item_name or item_name.strip() == '':
        raise ValidationError('物資品目は必須です')
    
    supplies_table.delete_item(
        Key={
            'shelter_id': shelter_id,
            'item_name': item_name
        }
    )
    
    return {
        'message': '物資情報を削除しました',
        'shelter_id': shelter_id,
        'item_name': item_name
    }

def delete_shelter(shelter_id):
    """
    避難所を削除する

    Args:
        shelter_id: 避難所ID

    Returns:
        dict: 削除結果
    """
    if not shelter_id or shelter_id.strip() == '':
        raise ValidationError('避難所IDは必須です')
    
    # 避難所が存在するか確認
    if not check_shelter_exists(shelter_id):
        raise ValidationError(f'避難所ID「{shelter_id}」は存在しません')
    
    # 避難所を削除
    table.delete_item(
        Key={'shelterID': shelter_id}
    )
    
    # 関連する物資も削除
    response = supplies_table.query(
        KeyConditionExpression='shelter_id = :sid',
        ExpressionAttributeValues={':sid': shelter_id}
    )
    
    deleted_supplies_count = 0
    for item in response.get('Items', []):
        supplies_table.delete_item(
            Key={
                'shelter_id': shelter_id,
                'item_name': item['item_name']
            }
        )
        deleted_supplies_count += 1
    
    return {
        'message': '避難所を削除しました',
        'shelter_id': shelter_id,
        'deleted_supplies_count': deleted_supplies_count
    }



# ステータス遷移ルール
VALID_TRANSITIONS = {
    'pending':   ['approved', 'rejected'],
    'approved':  ['shipped'],
    'shipped':   ['delivered'],
    'rejected':  [],
    'delivered': []
}

def validate_status_transition(current_status, new_status):
    """ステータス遷移の妥当性を検証する"""
    if new_status not in VALID_TRANSITIONS.get(current_status, []):
        raise ValidationError(f'無効なステータス遷移です: {current_status} → {new_status}')

def create_request(data):
    """物資補充要請を作成する（status=pending）"""
    required = ['shelter_id', 'item_name', 'quantity', 'urgency']
    for field in required:
        if not data.get(field):
            raise ValidationError(f'{field} は必須です')

    urgency = data['urgency']
    if urgency not in ['high', 'medium', 'low']:
        raise ValidationError('urgency は high / medium / low のいずれかです')

    try:
        quantity = int(data['quantity'])
        if quantity <= 0:
            raise ValidationError('数量は1以上である必要があります')
    except (ValueError, TypeError):
        raise ValidationError('数量は数値である必要があります')

    now = datetime.utcnow().isoformat() + 'Z'
    # request_id: REQ-YYYYMMDD-HHMMSS-shelterID
    date_str = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    request_id = f"REQ-{date_str}-{data['shelter_id']}"

    item = {
        'request_id': request_id,
        'shelter_id': data['shelter_id'],
        'municipality_id': data.get('municipality_id', ''),
        'item_name': data['item_name'],
        'quantity': Decimal(str(quantity)),
        'urgency': urgency,
        'status': 'pending',
        'created_at': now,
        'updated_at': now
    }
    requests_table.put_item(Item=item)

    return {**item, 'quantity': quantity}

def get_requests(shelter_id=None, status=None):
    """要請一覧を取得する（フィルタ対応）"""
    response = requests_table.scan()
    items = response.get('Items', [])

    results = []
    for item in items:
        if shelter_id and item.get('shelter_id') != shelter_id:
            continue
        if status and item.get('status') != status:
            continue
        results.append({
            'request_id': item.get('request_id', ''),
            'shelter_id': item.get('shelter_id', ''),
            'municipality_id': item.get('municipality_id', ''),
            'item_name': item.get('item_name', ''),
            'quantity': int(float(item.get('quantity', 0))),
            'urgency': item.get('urgency', 'medium'),
            'status': item.get('status', 'pending'),
            'created_at': item.get('created_at', ''),
            'updated_at': item.get('updated_at', '')
        })

    # 作成日時の降順でソート
    results.sort(key=lambda x: x['created_at'], reverse=True)
    return {'requests': results}

def update_request_status(request_id, new_status, shelter_id=None, item_name=None, quantity=None):
    """要請ステータスを更新する（遷移バリデーション付き）"""
    if not request_id:
        raise ValidationError('request_id は必須です')

    response = requests_table.get_item(Key={'request_id': request_id})
    if 'Item' not in response:
        raise ValidationError(f'要請ID「{request_id}」が見つかりません')

    current = response['Item']
    current_status = current.get('status', '')
    validate_status_transition(current_status, new_status)

    now = datetime.utcnow().isoformat() + 'Z'
    requests_table.update_item(
        Key={'request_id': request_id},
        UpdateExpression='SET #s = :s, updated_at = :u',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':s': new_status, ':u': now}
    )

    # 受領確認（shipped→delivered）の場合、物資在庫を加算
    if new_status == 'delivered':
        sid = shelter_id or current.get('shelter_id', '')
        iname = item_name or current.get('item_name', '')
        qty = quantity or int(float(current.get('quantity', 0)))
        if sid and iname and qty > 0:
            try:
                existing = supplies_table.get_item(Key={'shelter_id': sid, 'item_name': iname})
                current_qty = int(float(existing.get('Item', {}).get('quantity', 0)))
                supplies_table.put_item(Item={
                    'shelter_id': sid,
                    'item_name': iname,
                    'quantity': Decimal(str(current_qty + qty)),
                    'updated_at': now
                })
            except Exception as e:
                logger.warning(f"在庫加算エラー: {str(e)}")

    return {'request_id': request_id, 'status': new_status, 'updated_at': now}

def get_warehouses(warehouse_id=None):
    """倉庫在庫を取得する"""
    response = warehouse_table.scan()
    items = response.get('Items', [])

    warehouses_dict = {}
    for item in items:
        wid = item.get('warehouse_id', '')
        if warehouse_id and wid != warehouse_id:
            continue
        if wid not in warehouses_dict:
            warehouses_dict[wid] = {
                'warehouse_id': wid,
                'warehouse_name': item.get('warehouse_name', ''),
                'location': item.get('location', ''),
                'items': []
            }
        warehouses_dict[wid]['items'].append({
            'item_name': item.get('item_name', ''),
            'quantity': int(float(item.get('quantity', 0))),
            'updated_at': item.get('updated_at', '')
        })

    return {'warehouses': list(warehouses_dict.values())}

def update_warehouse_inventory(warehouse_id, item_name, delta):
    """倉庫在庫を更新する（減算時は負チェック付き）"""
    if not warehouse_id or not item_name:
        raise ValidationError('warehouse_id と item_name は必須です')

    try:
        delta = int(delta)
    except (ValueError, TypeError):
        raise ValidationError('delta は数値である必要があります')

    response = warehouse_table.get_item(Key={'warehouse_id': warehouse_id, 'item_name': item_name})
    current_qty = int(float(response.get('Item', {}).get('quantity', 0)))

    if current_qty + delta < 0:
        raise ValidationError(f'在庫が不足しています（現在: {current_qty}, 要求減算: {abs(delta)}）')

    now = datetime.utcnow().isoformat() + 'Z'
    existing = response.get('Item', {})
    warehouse_table.put_item(Item={
        'warehouse_id': warehouse_id,
        'item_name': item_name,
        'warehouse_name': existing.get('warehouse_name', ''),
        'location': existing.get('location', ''),
        'quantity': Decimal(str(current_qty + delta)),
        'updated_at': now
    })

    return {'warehouse_id': warehouse_id, 'item_name': item_name, 'quantity': current_qty + delta, 'updated_at': now}


def chat_with_bedrock(user_message):
    """
    Amazon Bedrockを使ってチャット応答を生成する
    """
    # Bedrockクライアントを関数内で初期化（リージョン明示）
    bedrock_client = boto3.client('bedrock-runtime', region_name='ap-northeast-1')

    # 現在の避難所データを取得
    shelters_response = table.scan()
    shelters = shelters_response.get('Items', [])

    # 現在の物資データを取得
    supplies_response = supplies_table.scan()
    supplies_items = supplies_response.get('Items', [])

    # 避難所データを整形
    shelter_summary = []
    for s in shelters:
        capacity = float(s.get('capacity', 0))
        occupancy = float(s.get('current_occupancy', 0))
        rate = round((occupancy / capacity * 100)) if capacity > 0 else 0

        phase_map = {'primary': '1次', 'secondary_short': '1.5次', 'secondary': '2次'}
        type_map = {'designated': '指定避難所', 'voluntary': '自主避難所'}

        shelter_summary.append({
            'ID': s.get('shelterID', ''),
            '名称': s.get('shelterName', ''),
            '住所': s.get('address', '未登録'),
            '種別': type_map.get(s.get('shelter_type', ''), '未設定'),
            '段階': phase_map.get(s.get('shelter_phase', ''), '未設定'),
            '収容人数': int(capacity),
            '現在の避難者数': int(occupancy),
            '使用率': f'{rate}%',
            '状態': s.get('status', 'OPEN'),
            '電話番号': s.get('phone_number', '未登録'),
            '担当職員': s.get('staff', [])
        })

    # 物資データを整形
    supplies_by_shelter = {}
    for item in supplies_items:
        sid = item.get('shelter_id', '')
        if sid not in supplies_by_shelter:
            supplies_by_shelter[sid] = []
        supplies_by_shelter[sid].append({
            '品目': item.get('item_name', ''),
            '数量': int(float(item.get('quantity', 0)))
        })

    # システムプロンプト
    system_prompt = f"""あなたは避難所管理システムのアシスタントです。
以下の現在のデータを元に、自治体職員の質問に日本語で正確に答えてください。

## 現在の避難所データ
{json.dumps(shelter_summary, ensure_ascii=False, indent=2)}

## 現在の物資データ（避難所IDごと）
{json.dumps(supplies_by_shelter, ensure_ascii=False, indent=2)}

## 回答のルール
- 必ず上記のデータのみを根拠に回答してください
- データにない情報は「登録されていません」と答えてください
- 数値の比較や集計が必要な場合は正確に計算してください
- 簡潔かつ明確に答えてください
- 表形式が適切な場合はMarkdownの表を使ってください"""

    logger.info(f"Calling Bedrock with model: amazon.nova-lite-v1:0")

    request_body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": f"{system_prompt}\n\n質問: {user_message}"
                    }
                ]
            }
        ],
        "inferenceConfig": {
            "maxTokens": 1024
        }
    }

    response = bedrock_client.invoke_model(
        modelId='amazon.nova-lite-v1:0',
        body=json.dumps(request_body)
    )

    response_body = json.loads(response['body'].read())
    logger.info(f"Bedrock response keys: {list(response_body.keys())}")
    answer = response_body['output']['message']['content'][0]['text']

    return {'answer': answer}



def authenticate_user(user_id, password):
    """ユーザー認証"""
    try:
        response = users_table.get_item(Key={'userID': user_id})
        user = response.get('Item')
        if not user:
            return None
        if user.get('password') != password:
            return None
        return {
            'userID': user['userID'],
            'name': user.get('name', ''),
            'role': user.get('role', 'field')
        }
    except Exception as e:
        logger.error(f"Auth error: {str(e)}")
        return None


def lambda_handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")
    body = {}
    statusCode = 200
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }

    try:
        route_key = event.get('routeKey', '')
        
        # OPTIONSリクエストの処理（CORSプリフライト）
        if route_key.startswith("OPTIONS"):
            return {
                "statusCode": 200,
                "headers": headers,
                "body": json.dumps({})
            }

        # 認証API
        if route_key == "POST /auth":
            requestJSON = json.loads(event.get('body', '{}'))
            user_id = requestJSON.get('userID', '').strip()
            password = requestJSON.get('password', '').strip()
            if not user_id or not password:
                statusCode = 400
                body = {'error': 'IDとパスワードを入力してください'}
            else:
                user = authenticate_user(user_id, password)
                if user:
                    body = {'success': True, 'user': user}
                else:
                    statusCode = 401
                    body = {'error': 'IDまたはパスワードが正しくありません'}

        # 避難所管理API - 全件取得
        elif route_key == "GET /items":
            response = table.scan()
            items = response.get("Items", [])
            responseBody = []
            for item in items:
                shelter_data = {
                    'shelterID': item.get('shelterID', ''),
                    'shelterName': item.get('shelterName', ''),
                    'capacity': float(item.get('capacity', 0)),
                    'current_occupancy': float(item.get('current_occupancy', 0)),
                    'status': item.get('status', 'OPEN')
                }
                
                # 住所が存在する場合は追加
                if 'address' in item:
                    shelter_data['address'] = item['address']
                
                # 避難所種別が存在する場合は追加
                if 'shelter_type' in item:
                    shelter_data['shelter_type'] = item['shelter_type']
                
                # 避難段階が存在する場合は追加
                if 'shelter_phase' in item:
                    shelter_data['shelter_phase'] = item['shelter_phase']
                
                # 緯度・経度が存在する場合は追加
                if 'latitude' in item:
                    shelter_data['latitude'] = float(item['latitude'])
                if 'longitude' in item:
                    shelter_data['longitude'] = float(item['longitude'])
                
                # 電話番号が存在する場合は追加
                if 'phone_number' in item:
                    shelter_data['phone_number'] = item['phone_number']
                
                # 担当職員が存在する場合は追加
                if 'staff' in item:
                    shelter_data['staff'] = item['staff']
                
                responseBody.append(shelter_data)
            body = responseBody

        # 避難所管理API - 登録・更新
        elif route_key == "PUT /items":
            requestJSON = json.loads(event.get('body', '{}'))
            item_data = {
                'shelterID': requestJSON.get('shelterID', 'unknown'),
                'shelterName': requestJSON.get('shelterName', 'unknown'),
                'capacity': Decimal(str(requestJSON.get('capacity', 0))),
                'current_occupancy': Decimal(str(requestJSON.get('current_occupancy', 0))),
                'status': requestJSON.get('status', 'OPEN')
            }
            
            # 住所が提供されている場合は保存
            if requestJSON.get('address'):
                item_data['address'] = requestJSON.get('address')
            
            # 避難所種別が提供されている場合は保存
            if requestJSON.get('shelter_type'):
                item_data['shelter_type'] = requestJSON.get('shelter_type')
            
            # 避難段階が提供されている場合は保存
            if requestJSON.get('shelter_phase'):
                item_data['shelter_phase'] = requestJSON.get('shelter_phase')
            
            # 緯度・経度が提供されている場合は保存
            if requestJSON.get('latitude') is not None:
                item_data['latitude'] = Decimal(str(requestJSON.get('latitude')))
            if requestJSON.get('longitude') is not None:
                item_data['longitude'] = Decimal(str(requestJSON.get('longitude')))
            
            # 電話番号が提供されている場合は保存
            if requestJSON.get('phone_number'):
                item_data['phone_number'] = requestJSON.get('phone_number')
            
            # 担当職員が提供されている場合は保存
            if requestJSON.get('staff') is not None:
                item_data['staff'] = requestJSON.get('staff')
            
            table.put_item(Item=item_data)
            body = 'Put item ' + requestJSON.get('shelterID', 'unknown')

        # 避難所管理API - 削除
        elif route_key == "DELETE /items":
            query_params = event.get('queryStringParameters', {}) or {}
            shelter_id = query_params.get('shelterID', '')
            
            result = delete_shelter(shelter_id)
            body = result
            logger.info(f"Shelter deleted: {result}")

        # 物資管理API - 物資登録
        elif route_key == "POST /supplies":
            requestJSON = json.loads(event.get('body', '{}'))
            validate_supply_input(requestJSON)
            
            # 避難所の存在確認
            shelter_id = requestJSON['shelter_id']
            if not check_shelter_exists(shelter_id):
                raise ValidationError(f'避難所ID「{shelter_id}」は登録されていません。先に避難所を登録してください。')
            
            result = register_supply(
                shelter_id,
                requestJSON['item_name'],
                int(requestJSON['quantity'])
            )
            body = {
                'message': '物資情報を登録しました',
                **result
            }
            logger.info(f"Supply registered: {result}")

        # 物資管理API - 特定避難所の物資取得
        elif route_key == "GET /supplies":
            query_params = event.get('queryStringParameters', {}) or {}
            shelter_id = query_params.get('shelter_id', '')
            
            result = get_supplies_by_shelter(shelter_id)
            body = result

        # 物資管理API - 全避難所の物資取得
        elif route_key == "GET /supplies/all":
            result = get_all_supplies()
            body = result

        # 物資管理API - 物資削除
        elif route_key == "DELETE /supplies":
            query_params = event.get('queryStringParameters', {}) or {}
            shelter_id = query_params.get('shelter_id', '')
            item_name = query_params.get('item_name', '')
            
            result = delete_supply(shelter_id, item_name)
            body = result
            logger.info(f"Supply deleted: {result}")

        # 物資補充要請API - 要請作成
        elif route_key == "POST /requests":
            requestJSON = json.loads(event.get('body', '{}'))
            result = create_request(requestJSON)
            body = result
            statusCode = 201
            logger.info(f"Request created: {result.get('request_id')}")

        # 物資補充要請API - 要請一覧取得
        elif route_key == "GET /requests":
            query_params = event.get('queryStringParameters', {}) or {}
            shelter_id = query_params.get('shelter_id')
            status_filter = query_params.get('status')
            result = get_requests(shelter_id=shelter_id, status=status_filter)
            body = result

        # 物資補充要請API - ステータス更新
        elif route_key == "PUT /requests":
            requestJSON = json.loads(event.get('body', '{}'))
            request_id = requestJSON.get('request_id', '')
            new_status = requestJSON.get('status', '')
            if not new_status:
                raise ValidationError('status は必須です')
            result = update_request_status(
                request_id, new_status,
                shelter_id=requestJSON.get('shelter_id'),
                item_name=requestJSON.get('item_name'),
                quantity=requestJSON.get('quantity')
            )
            body = result
            logger.info(f"Request status updated: {request_id} -> {new_status}")

        # 倉庫在庫API - 倉庫一覧取得
        elif route_key == "GET /warehouses":
            query_params = event.get('queryStringParameters', {}) or {}
            warehouse_id = query_params.get('warehouse_id')
            result = get_warehouses(warehouse_id=warehouse_id)
            body = result

        # 倉庫在庫API - 在庫更新
        elif route_key == "PUT /warehouses":
            requestJSON = json.loads(event.get('body', '{}'))
            result = update_warehouse_inventory(
                requestJSON.get('warehouse_id', ''),
                requestJSON.get('item_name', ''),
                requestJSON.get('delta', 0)
            )
            body = result
            logger.info(f"Warehouse inventory updated: {result}")

        # チャットAPI - Bedrock連携
        elif route_key == "POST /chat":
            requestJSON = json.loads(event.get('body', '{}'))
            user_message = requestJSON.get('message', '').strip()
            
            if not user_message:
                raise ValidationError('メッセージは必須です')
            
            result = chat_with_bedrock(user_message)
            body = result
            logger.info(f"Chat response generated")

        else:
            statusCode = 400
            body = {'error': 'Unsupported route: ' + route_key}
            logger.warning(f"Unsupported route: {route_key}")

    except ValidationError as e:
        statusCode = 400
        body = {'error': str(e)}
        logger.warning(f"Validation error: {str(e)}")
    except boto3.exceptions.Boto3Error as e:
        statusCode = 500
        body = {'error': 'データベースエラーが発生しました'}
        logger.error(f"Database error: {str(e)}", exc_info=True)
    except Exception as e:
        statusCode = 500
        body = {'error': '内部サーバーエラーが発生しました'}
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)

    return {
        "statusCode": statusCode,
        "headers": headers,
        "body": json.dumps(body, ensure_ascii=False)
    }