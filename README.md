# gns3lab

GNS3の構築を自動化するCLIツール。containerlabのように、トポロジをYAMLで定義して `deploy` / `destroy` するだけで使えます。

## セットアップ

```
pip install -e .
```

`gns3lab_config.yml.example` をコピーして `gns3lab_config.yml` を作成し、GNS3サーバーの接続情報を入力してください（このファイルはgit管理外です）。

```yaml
server:
  base: http://<GNS3サーバー>:3080/v2
  user: <ユーザー名>
  password: <パスワード>
```

同様に `gns3lab_templates.yml.example` をコピーして `gns3lab_templates.yml` を作成してください
（こちらもgit管理外）。トポロジーYAMLの `template:` に書く役割名と、あなたのGNS3サーバーに
実際に登録されているテンプレート名との対応表です。詳しくは後述の「テンプレート対応表」を参照してください。
GUIを使う場合はファイルを手で作らなくても「テンプレート対応」タブから作成・編集できます。

## 別の環境（他の人のPC）へ移植するとき

このツールはリポジトリのコードだけでなく、**接続先のGNS3サーバー側の状態**にも依存します。
移植先ごとに1〜3すべてを合わせる必要があります。

### 1. アクセス先とアカウント（`gns3lab_config.yml`）

- `gns3lab_config.yml` は `.gitignore` 対象なので、`git clone` しただけでは付いてきません。
  フォルダごとコピーして渡す場合は、実際のパスワードが平文で入っているため、渡す前に
  `gns3lab_config.yml` を削除して `gns3lab_config.yml.example` だけ残してください。
- 移植先では `gns3lab_config.yml.example` をコピーして `gns3lab_config.yml` を作り、その環境に
  合わせて書き換えます。

  | 項目 | 確認方法 |
  |---|---|
  | `base`（GNS3サーバーのURL） | GNS3 GUIの `Edit > Preferences > Server > Local Server` にある Host/Port。同じPC上でGNS3を動かす場合は `http://127.0.0.1:<port>/v2` |
  | `user` / `password` | 同じ画面の Authentication欄。または `%APPDATA%\GNS3\<version>\gns3_server.ini`（GNS3 2.xの場合）の `[Server]` セクションにある `user` / `password`（`auth = True` の場合のみ必要。`auth = False` なら認証自体不要で `user`/`password` は空でも動きます） |

- 実行時にこのファイルが無いと `設定ファイルが見つかりません` というエラーで即終了するので、
  移植直後に何か動かない場合はまずここを確認してください。

### 2. テンプレートの登録（GNS3サーバー側）

トポロジーYAMLの `template:` は**役割名**（例: `ios-router`）で、下記3のテンプレート対応表を
介して実テンプレート名に解決されます。解決先の実テンプレートが移植先のGNS3サーバーに
登録されていなければ `deploy` はテンプレート未検出のエラーで失敗します。

- 移植先でまず次を実行し、実際に使えるテンプレート名を確認します。

  ```
  gns3lab templates
  ```

- `c3725` などのDynamips系ルータテンプレートは、**移植先のGNS3に同じIOSイメージが登録されて
  初めて使えます**。GNS3自体はCisco IOSイメージを配布していない（ライセンスの都合）ため、
  IOSイメージは利用者側で用意し、GNS3 GUIの `Edit > Preferences > Dynamips > IOS Routers`
  （または `File > Import appliance` でのアプライアンス取り込み）からテンプレートとして
  登録しておく必要があります。`VPCS` / `Ethernet switch` / `NAT` はGNS3に標準搭載されている
  ため追加作業は不要です。

### 3. テンプレート対応表（`gns3lab_templates.yml`）

`gns3lab_config.yml` と同様に `.gitignore` 対象・環境ごとに固有の必須ファイルです。
`gns3lab_templates.yml.example` をコピーして作成するか、GUIの「テンプレート対応」タブで作成します。

```yaml
templates:
  vpcs: VPCS
  switch: Ethernet switch
  nat: NAT
  ios-router: c3725                          # 環境によっては c7200 等に読み替え
  iosv-router: "Cisco IOSv 15.9(3)M12"
  asav-firewall: "Cisco ASAv 9.24.1 CML"
```

- トポロジーYAML側の `template:` は常にこの対応表のキー（役割名）を書きます。
  `deploy` 実行時にこのファイルを見て実際のテンプレート名に解決してからノードを作成します。
- 対応表に無い役割名が指定された場合、または対応表ファイル自体が無い場合は、
  `deploy` はエラーで停止します（フォールバックはありません）。
- 対応表のパスは `gns3lab deploy -m <パス>` で変更できます（省略時はカレントディレクトリの
  `gns3lab_templates.yml`）。
- GUI（`gns3lab-gui`）の「テンプレート対応」タブなら、YAMLを手で書かなくても
  役割名と実テンプレート名を表形式で編集でき、実テンプレート名は「サーバーのテンプレート
  一覧を取得」ボタンでドロップダウンから選べます。「トポロジ編集タブから未登録の役割名を追加」
  ボタンで、今編集中のトポロジーYAMLが使っている役割名のうち未登録のものだけを自動検出できます。
- **注意**: 役割名はあくまで名前解決のためのエイリアスです。`config:` に書く投入内容は
  機種依存（例: c3725系は `FastEthernet0/0`、IOSv系は `GigabitEthernet0/0`）なので、
  対応表で全く異なるプラットフォームに差し替えると `config:` の内容と機種が一致しなくなります。
  同じインターフェース構成・CLI体系を持つ機種同士（例: `c3725` ↔ `c7200`）の読み替えに使ってください。

## 使い方

### 1. 使えるテンプレート名を確認し、対応表に登録する

```
gns3lab templates
```

`name` 列の値を `gns3lab_templates.yml` の対応表（役割名 → 実テンプレート名）に登録します。
GUIなら「テンプレート対応」タブで、ドロップダウンから選んで登録できます。

### 2. トポロジをYAMLで定義する

`examples/topology.yml` を参考に、好きな構成のファイルを作成します。
`template:` には `gns3lab_templates.yml` に登録した役割名を書きます。

```yaml
name: mixed_lab

nodes:
  R1:
    template: l3-switch
    x: 0
    y: -200
  SW1:
    template: l2-switch
    x: 0
    y: 0
  PC1:
    template: vpcs
    x: -150
    y: 200

links:
  - [R1:0/0, SW1:0/0]
  - [SW1:0/1, PC1:0/0]
```

```yaml
# gns3lab_templates.yml 側
templates:
  l3-switch: Cisco_L3SW
  l2-switch: Cisco_L2SW
  vpcs: VPCS
```

- `nodes`: ノード名 → 役割名（`template:`）・座標
- `links`: `[ノード名:adapter/port, ノード名:adapter/port]` の形式で2端点を指定
- 対応表に無い役割名を指定すると `deploy` はエラーで停止します。詳しくは前述の
  「3. テンプレート対応表」を参照してください。

トポロジー例は `examples/` ディレクトリにまとめています:

- `examples/topology.yml`: MPLS L3VPN検証ラボ（基本的な構成例）
- `examples/financial_wan_topology.yml`: 東京DC(本番)/大阪DC(DR)/本店をWAN経由で接続し、ASAvファイアウォールでDMZを分離した金融系トポロジー
- `examples/wan_gre_mpls_redundancy.yml`: MPLSプライマリ経路 + GRE over IPsec VPNバックアップ経路によるWAN冗長化トポロジー
  - 設計書: [基本設計書](docs/wan-redundancy-basic-design.md) / [詳細設計書](docs/wan-redundancy-detailed-design.md)
- `examples/nat_topology.yml`: 内部LAN(PC1/PC2/SVR1) - NATルーター(R1) - 外部ホスト(EXT-PC) による
  動的PAT(overload)と静的NATの検証トポロジー

### 2b. ノードに初期設定を持たせる（config自動投入）

各ノードに `config:` を書いておくと、`deploy` でノードを起動した直後にコンソール（telnet）
経由でCLIを自動投入します。GNS3のREST APIには設定注入用の専用エンドポイントが無いため、
実機のコンソールに接続してコマンドを打鍵する方式で代用しています。

```yaml
nodes:
  R1:
    template: ios-router
    x: 0
    y: 0
    config: |
      hostname R1
      interface FastEthernet0/0
       ip address 10.0.0.1 255.255.255.0
       no shutdown

  PC1:
    template: vpcs
    x: 0
    y: 200
    config: |
      ip 10.0.0.10 255.255.255.0 10.0.0.1
      save
```

- 対応ノード種別: dynamips/IOU系ルータ（`enable` → `configure terminal` → 設定投入 →
  `end` → `write memory`）、VPCS（プロンプト待ちで行ごとに投入）。それ以外の種別は
  自動投入できないため警告を出してスキップします。
- enableパスワードが設定されているテンプレートの場合は `enable_password:` をノードに
  追加してください。
- 投入結果はノードごとに `ノード名: OK` / `ノード名: 失敗 - 理由` の形式で表示され、
  1ノードの失敗が他ノードの投入を止めることはありません。
- タイミング依存の自動操作のため、初回はGNS3のWebUIでコンソールを開いて実際に
  投入されたか目視確認することをおすすめします（dynamips系ノードは起動〜プロンプト
  表示までに数十秒かかることがあり、最大180秒待った上でタイムアウトします）。

### 3. デプロイ

```
gns3lab deploy examples/topology.yml
```

プロジェクト作成 → ノード作成 → リンク作成 → 全ノード起動 → (config定義があれば)設定投入、
まで一括で行います。

- `--no-start`: ノードを起動しない（起動しないため設定投入も自動でスキップされます）
- `--no-config`: ノードは起動するが、`config:` の自動投入は行わない
- `-m/--template-map`: テンプレート対応表のパスを指定（省略時はカレントディレクトリの
  `gns3lab_templates.yml`。ファイルが無い場合や、使われている役割名が対応表に無い場合は
  エラーで停止します）

```
gns3lab deploy examples/topology.yml --no-config
```

同名プロジェクトが既に存在する場合はエラーになります（先に `destroy` してください）。

### 3b. 起動中のプロジェクトへ設定だけ再投入する

`examples/topology.yml` の `config:` を書き換えた後、プロジェクトを作り直さずに設定だけ
再投入したい場合は `configure` を使います。

```
gns3lab configure examples/topology.yml
```

- `topology.yml` の `name` からプロジェクトを検索し、既存ノードの一覧を取得した上で、
  `config:` が定義されているノードへ再投入します。
- プロジェクトが見つからない場合はエラーになります（先に `deploy` してください）。
- ノードが存在しない、または停止中の場合はそのノードだけスキップし、他のノードへの
  投入は続行します。

### 4. 状態確認

```
gns3lab list
```

サーバー上の全プロジェクトを name / status / project_id で一覧表示します。

指定したプロジェクトの中身（ノードごとのテンプレート/status/コンソールポートと、
リンクの接続関係）まで見たい場合は `status` を使います。

```
gns3lab status mixed_lab
```

```
Project: mixed_lab  status=opened  project_id=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

name                 template                     status     console
------------------------------------------------------------------------------------------
PC1                  VPCS                         started    127.0.0.1:5001
R1                   Cisco_L3SW                    started    127.0.0.1:5002
SW1                  Cisco_L2SW                    started    127.0.0.1:5003

links (2):
  R1:0/0 -- SW1:0/0
  SW1:0/1 -- PC1:0/0
```

トポロジーYAMLを介さず、**GNS3サーバー側の現在の実際の状態**を直接取得して表示するため、
手動でノードを追加/変更したプロジェクトの状態確認や、`deploy` が失敗した際の途中経過確認にも使えます。

### 5. 削除

```
gns3lab destroy mixed_lab
```

プロジェクト名（または project_id）を指定すると、全ノードを停止してからプロジェクトを削除します。

プロジェクト名を覚えていなくても、`deploy` に使ったトポロジーファイルをそのまま渡せます
（ファイル内の `name:` を自動で読み取ります）。

```
gns3lab destroy examples/nat_topology.yml
```

## GUI（サブコマンドをタブで選択）

コマンドを覚えなくても使えるGUI版があります。

```
gns3lab-gui
```

（`pip install -e .` 済みであれば上記コマンドで起動します）

タブ構成:

- **トポロジ編集**: 起動時に最初に開くタブ。左側でYAMLを直接編集でき、入力を止めて
  少し経つと右側の構成図（ノード種別ごとに色分けしたCanvas図）が自動的に再描画されます。
  YAMLが壊れていてもアプリはクラッシュせず、右下にエラー内容が表示されるだけです。
  「開く...」「保存」ボタンでファイルの読み込み・上書き保存ができます。
- **deploy**: トポロジファイルとテンプレート対応表（`gns3lab_templates.yml`）を指定して
  実行。「起動しない (--no-start)」「設定を投入しない (--no-config)」のチェックボックスと、
  「Deploy 実行」ボタンあり。隣の「設定を再投入 (configure)」ボタンは、既存プロジェクトを
  作り直さずに `config:` だけを再投入します（`gns3lab configure` と同じ）。
- **destroy**: プロジェクト名（またはproject_id）を指定して停止・削除。「一覧を更新」ボタンで
  サーバー上の既存プロジェクト名をドロップダウンから選べるほか、「トポロジファイルから選択...」
  でトポロジYAMLを指定すればその `name:` を自動入力します。
- **list**: 「List 更新」でサーバー上の全プロジェクト（name/status/project_id）を表形式で表示。
  行を選択して「選択したプロジェクトを削除」を押すと、確認ダイアログの後にそのプロジェクトを
  停止・削除します（destroyタブに切り替える必要はありません）。
- **status**: プロジェクト名（またはproject_id）を指定して、ノード（テンプレート/status/
  コンソールポート）とリンクの一覧を表示（`gns3lab status` と同じ）。
- **templates**: 利用可能なテンプレート名を一覧表示。
- **テンプレート対応**: `gns3lab_templates.yml`（役割名 → 実テンプレート名）をGUIで編集。
  「サーバーのテンプレート一覧を取得」でGNS3サーバー上の実テンプレート名をドロップダウンの
  選択肢として取得し、「行を追加」で役割名と実テンプレート名の組を追加、行右の「削除」で
  1行だけ削除できます。「トポロジ編集タブから未登録の役割名を追加」を押すと、トポロジ編集
  タブで今開いているYAMLが使っている役割名のうち対応表に無いものだけを自動検出して
  空欄の行として追加します。「保存」で指定パスに書き出します。

実行結果は下部の出力欄にリアルタイム表示されます。

## exe化（Pythonなし環境向け）

Windows単体exeとしてビルドできます。配布先にPythonのインストールは不要です。

```
pip install pyinstaller

# CLI版
pyinstaller --onefile --name gns3lab --paths src scripts/build_entry.py

# GUI版
pyinstaller --onefile --windowed --name gns3lab-gui --paths src scripts/build_gui_entry.py
```

`dist/gns3lab.exe` / `dist/gns3lab-gui.exe` が生成されます。`gns3lab_config.yml`・
`gns3lab_templates.yml`・`topology.yml` を同じフォルダに置いて実行してください。

```
gns3lab.exe templates
gns3lab.exe deploy topology.yml
gns3lab.exe list
gns3lab.exe status mixed_lab
gns3lab.exe destroy mixed_lab
```

GUI版はダブルクリックで起動し、タブでサブコマンドを選べます。
