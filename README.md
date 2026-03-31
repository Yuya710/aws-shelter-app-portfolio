# 避難所統合管理システム

大規模災害発生時における避難所の運営を支援するWebアプリケーションです。自治体本部・現場担当・中央物流の3つの職能に分かれた職員が、それぞれの役割に応じた画面からリアルタイムで情報を共有・更新できます。

## 開発背景

日本は地震・津波・台風など自然災害が多く、避難所運営における情報の分散・伝達の遅れが課題となっています。本システムは、紙やExcelで管理されがちな避難所情報・物資在庫・補充要請をデジタル化し、関係者間の情報共有を効率化することを目的として開発しました。

## デモ

https://staging.d1qmuvazgw6sq6.amplifyapp.com/login.html

以下のデモアカウントで全機能を閲覧できます。

| 職員ID | パスワード | ロール |
|--------|-----------|--------|
| DEV001 | dev-password | developer（全モードアクセス可） |

## 主な機能

- 避難所の開設状況・収容人数のリアルタイム管理
- 地図上への避難所ピン表示（Leaflet.js + OpenStreetMap）
- 物資在庫の3日分基準による自動不足検知・アラート
- 現場から本部への物資補充要請ワークフロー（承認 → 出荷 → 受領）
- Amazon Bedrockを活用したAIチャット（避難所・物資情報を自然言語で照会）
- 職員IDとロールベースのアクセス制御（admin / field / logistics）

## 画面構成

| ページ | ロール | 説明 |
|--------|--------|------|
| login.html | 全員 | 職員IDとパスワードでログイン |
| index.html | admin | 全避難所の状況一覧・地図・AIチャット |
| field.html | field | 担当避難所の避難者数・物資更新・補充要請 |
| logistics.html | logistics | 倉庫在庫管理・出荷処理 |
| shelters.html | admin | 避難所の登録・編集 |
| supplies.html | admin | 物資の登録・編集 |

## 技術スタック

| 区分 | 技術 |
|------|------|
| フロントエンド | HTML / JavaScript / Bootstrap 5 / Leaflet.js |
| バックエンド | AWS Lambda（Python） |
| API | Amazon API Gateway（HTTP API） |
| データベース | Amazon DynamoDB |
| AI | Amazon Bedrock（Nova Lite / ap-northeast-1） |
| ホスティング | AWS Amplify |
| 認証 | DynamoDB + sessionStorage（ロールベース） |

## アーキテクチャ

```
ブラウザ
  ├── AWS Amplify（フロントエンドホスティング）
  └── Amazon API Gateway
        └── AWS Lambda（Python・単一関数）
              ├── DynamoDB: shelterDB（避難所情報）
              ├── DynamoDB: ShelterSupplies（物資在庫）
              ├── DynamoDB: SupplyRequests（補充要請）
              ├── DynamoDB: WarehouseInventory（倉庫在庫）
              ├── DynamoDB: ShelterUsers（職員認証）
              └── Amazon Bedrock: Nova Lite（AIチャット）
```

## DynamoDBテーブル構成

| テーブル名 | PK | SK | 用途 |
|-----------|----|----|------|
| shelterDB | shelterID | - | 避難所基本情報 |
| ShelterSupplies | shelter_id | item_name | 物資在庫 |
| SupplyRequests | request_id | - | 補充要請 |
| WarehouseInventory | warehouse_id | item_name | 倉庫在庫 |
| ShelterUsers | userID | - | 職員認証 |

## AIチャットの仕組み

RAGに近い構成で実装しています。ユーザーが質問を送信すると、LambdaがDynamoDBから全避難所・全物資データをリアルタイムで取得し、システムプロンプトに注入してBedrockに送信します。これにより、常に最新の状況を反映した自然言語での回答が可能です。

## セットアップ

### 前提条件

- AWSアカウント
- 以下のサービスを手動で構築済みであること
  - API Gateway（HTTP API）
  - Lambda関数（Python）
  - DynamoDB（上記5テーブル）
  - Amplify

### デプロイ手順

1. `lambda_function.py` をLambdaコンソールにアップロード
2. フロントエンドファイルをzipにまとめてAmplifyにアップロード

```powershell
Compress-Archive -Path index.html, field.html, logistics.html, shelters.html, supplies.html, login.html, municipality -DestinationPath deploy.zip -Force
```

3. `ShelterUsers` テーブルに職員データを登録

```json
{
  "userID": {"S": "EMP001"},
  "password": {"S": "your-password"},
  "name": {"S": "氏名"},
  "role": {"S": "admin"}
}
```

## 注意事項

- パスワードは現在平文で保存されています。本番運用時はAmazon Cognitoへの移行を推奨します。
- APIエンドポイントURLはフロントエンドにハードコードされています。本番運用時は環境変数化を推奨します。

## 今後の改善案

- Amazon Cognitoによる認証強化（MFA・JWT）
- CloudFront導入によるCDNキャッシュ・DDoS対策
- AWS WAFによるAPIアクセス制御
- CloudWatch Alarmsによる監視・通知
- SAM / CDKによるInfrastructure as Code化
- PWA化によるオフライン対応
- LINE Notify等によるプッシュ通知

