"""根据只读结构快照、OpenAPI和已核对源码生成当前实现说明；不修改数据库。"""
import html
import json
from pathlib import Path
from applications.wrq.agent.schemas.skill_package_schema import SkillDeveloperForm

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'deliverables'
DB = json.loads((OUT / '开发者中心_最终后端_数据库结构快照_20261026.json').read_text('utf8'))
API = json.loads((OUT / '开发者中心_最终后端_OpenAPI快照_20261026.json').read_text('utf8'))
TEST = json.loads((OUT / '开发者中心_调试后续流程测试结果_20261026.json').read_text('utf8'))

def esc(value):
    return html.escape(str(value if value is not None else '—'))

def code(value):
    return '<code>' + esc(value) + '</code>'

def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>'+esc(h)+'</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows) + '</tbody></table></div>'

def note(text):
    return '<div class="note">'+text+'</div>'

def pre(value):
    return '<pre>'+esc(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))+'</pre>'

def bullets(items):
    return '<ul>'+''.join('<li>'+v+'</li>' for v in items)+'</ul>'

INFO = {
'keenrobot_skills': ('技能主表', '当前业务', '记录技能归属、当前版本和当前状态；正文按版本保存在表单表。', '创建、列表、保存修改、草稿删除、构建、登记调试、上线、下线。', {
 'id':'技能稳定编号。每次保存产生新版本，但技能编号不变；也是同事接口中的 skill_id。',
 'name':'当前名称的查询副本；未软删除的技能名称唯一，跨创建者生效；去首尾空格、大小写归一后不能重名。',
 'description':'当前版本描述的查询副本。修改时与新版本表单同时保存；历史描述在 forms 中。',
 'user_id':'创建人的平台用户编号，当前来自已验证 JWT；以字符串存储，不通过外键维护一套开发者中心用户资料。完整项目鉴权仍查询共享用户表。',
 'is_enabled':'是否可用，仅 ONLINE 为真。数据库 CHECK 将它与 display_status 约束在一起。',
 'display_status':'MySQL ENUM：DRAFT 草稿、DEBUGGING 调试中、DEBUG_SUCCESS 调试成功、DEBUG_FAILED 调试失败、ONLINE 已上线、OFFLINE 已下线。',
 'current_version_id':'指向技能版本表的整数主键，不是 1.0.0 这样的展示版本号。',
 'current_revision':'该技能自己的修订序号，从 1 开始。展示版本为 1.0.{revision-1}；不能由跨技能自增的版本主键直接计算。',
 'last_debug_run_id':'当前技能版本最近登记或上线采纳的任务编号；它本身不能证明任务已通过。',
 'last_debug_passed_at':'当前版本已被核实通过的时间标记；普通轮询不自动更新该字段，上线仍重新读取同事真实结果。',
 'published_at':'最近一次上线时间。以后编辑回草稿时仍可保留此历史时间，当前状态应看 display_status。',
 'offline_at':'最近一次下线时间，历史时间不代表当前状态。',
 'state':'0 正常、1 软删除。删除草稿只改此状态，历史记录保留；名称可重新使用。',
 'created_time':'首次创建技能的时间。', 'updated_time':'主表最近更新的时间，供列表排序。'}),
'keenrobot_skill_versions': ('技能版本元数据', '当前业务', '每次保存修改产生一版；记录修订、构建编号和构建包位置，正文不重复放在这里。', '创建/保存、构建、编辑定义、调试登记、上线校验。', {
 'id':'全库自增的版本整数主键。与同一技能内的 revision 是两个概念。', 'skill_id':'这一版属于哪个技能；外键关联 skills.id。',
 'version':'展示版本，例如修订 1 对应 1.0.0，修订 2 对应 1.0.1。', 'revision':'同一技能内递增的序号；(skill_id, revision) 唯一。',
 'build_id':'该保存版本实际生成的构建编号；未构建时为空。登记任务用它找到实际执行版本。',
 'package_storage_key':'该构建 ZIP 的服务端磁盘位置；当前不是云对象存储 URL。',
 'manifest_hash':'manifest.json 原始字节的 SHA256，用于记录构建清单摘要；文件内容另有各自 SHA256。',
 'created_by':'保存这一版的操作人平台编号。', 'created_time':'这一版保存的时间。', 'updated_time':'补齐构建信息等元数据的时间。已构建版本不被新修改覆盖。'}),
'keenrobot_skill_forms': ('技能版本表单正文', '当前业务', '一个技能版本对应一条表单，将原 config 拆成有含义的独立字段。', '保存表单、读取列表/定义、构建、修改 Markdown。', {
 'skill_version_id':'本表主键，同时是版本表外键，实现一版一份正文。', 'name':'这一版保存时的技能名称。',
 'skill_class_id':'所选技能大类编号，指向 skill_classes.id。', 'application_id':'门户应用编号；* 表示全应用适用。当前尚未配置门户目录时只提供 *，无本地应用表。',
 'description':'这一版的技能描述。', 'instructions':'这一版的执行指令；修改 Markdown 的接口也会提取其正文同步到此处。',
 'resource_usage':'本版统一资源使用说明；选择文件或知识库时服务校验必填。', 'compatibility':'可选运行环境要求，例如依赖包、Python 版本。',
 'technical_name':'构建目录/Skill 技术名；未指定时根据技能编号生成稳定名称。',
 'skill_markdown':'该版 SKILL.md 内容。首次构建会生成并保存；要编辑它应走 definition 接口，不能靠普通表单的同名兼容字段覆盖。'}),
'keenrobot_skill_classes': ('技能大类字典', '当前业务', '提供可选技能类别。', 'metadata、创建和修改的有效性校验。', {
 'id':'技能大类稳定编号。', 'name':'大类显示名称，数据库唯一。', 'is_enabled':'是否允许新表单选择；排序按编号，不存在 sort_order 字段。'}),
'keenrobot_resource_categories': ('资源用途字典', '当前业务', '回答文件用来做什么：参考资料、模板、静态资源、脚本。不是文件来自哪里。', 'metadata、文件上传/换版、构建目录分类、列表展示用途。', {
 'id':'用途整数编号，被文件及文件版本的 category_id 引用。', 'code':'稳定程序代码 reference / template / asset / script，代码唯一。',
 'name':'对应中文显示名称。', 'is_enabled':'是否允许选择该用途。'}),
'keenrobot_skill_uploaded_files': ('长期上传文件主表', '当前业务', '一份可持续换版的长期挂载文件，记录当前文件属性；不存沙箱临时需求文档。', '保存资源、文件换版、权限校验；与文件版本表配合。', {
 'id':'文件实体编号；换版不变，和文件版本 id 不同。', 'original_name':'当前原始文件名，通常已含后缀。',
 'extension':'另存的小写后缀，如 .docx；用于格式校验和查询。它与文件名有可推导关系，当前保留便于一致校验。',
 'mime_type':'根据文件名推断的 MIME 类型，可为空；不等同于已完成内容格式安全识别。', 'byte_size':'当前文件真实字节数，服务端流式读取统计，单文件及一次上传总量均不超过 50×1024×1024 字节。',
 'sha256':'当前原件字节的 SHA256；用于构建和下载时核对是否被替换。', 'storage_key':'当前原件在后端磁盘中的受控存储位置。',
 'uploaded_by':'这份文件最初上传人的平台编号，作为资源访问权限依据。', 'state':'ACTIVE 正常；MISSING 表示原件缺失的历史状态；DELETED 软删除。未实现独立文件删除接口。',
 'created_time':'文件实体最初建立时间。', 'deleted_at':'软删除时间，未删除时为空。', 'category_id':'当前文件用途编号，关联 resource_categories；不是来源类型。',
 'current_version_id':'指向当前文件版本的整数主键。', 'current_revision':'这份文件自身的修订序号，换版时加 1。'}),
'keenrobot_source_versions': ('长期文件版本', '当前业务', '每次文件上传或换版保存属性与原件位置，旧技能继续固定引用旧文件版本。', '资源上传/换版、下载原件、保存技能挂载、构建。', {
 'id':'文件版本主键。原件下载路径使用此编号，不使用文件主表编号。', 'file_id':'所属长期文件主表 id。', 'revision':'这份文件内的版本序号；(file_id, revision) 唯一。',
 'original_name':'本版原始文件名。', 'extension':'本版小写文件后缀。', 'mime_type':'本版根据文件名推断的 MIME 类型。',
 'byte_size':'本版原件真实大小。', 'sha256':'本版原件 SHA256；无法找回的历史原件可能为空。', 'storage_key':'本版原件所在的磁盘位置，换版不会覆盖旧位置。',
 'category_id':'本版的用途快照，关联用途字典；新文件版本改用途不反向修改旧版。', 'uploaded_by':'上传这一版的操作人编号。',
 'state':'本版原件状态 ACTIVE / MISSING / DELETED。', 'created_time':'这一版保存时间。', 'deleted_at':'这一版软删除时间；当前没有对外单独删除接口。'}),
'keenrobot_skill_resource_bindings': ('技能版本与资源挂载关联', '当前业务', '回答“哪个技能的哪一版，使用了哪个来源资源/文件版本”。', '创建、保存、读取详情、构建与历史追溯。', {
 'id':'挂载关联自身的主键。', 'skill_version_id':'被挂载资源的技能版本主键。',
 'source_type':'来源代码：新上传文件为 upload，整库挂载为 knowledge_base；保留 knowledge_document 等旧来源兼容语义。这是来源，绝不是四种用途。',
 'source_id':'来源对象编号；upload 时是 file_id 的字符串，知识库时是知识库编号。',
 'source_version':'来源版本标记；上传文件为文件 revision 的字符串。知识库现有路径使用其 revision（缺失则默认 1）转版本号，不代表完整知识库历史版本系统。',
 'file_id':'上传文件主表编号；非文件来源可以为空。与 source_version_id 配套。', 'display_name':'建立挂载时保存的显示名称快照。',
 'usage_text':'该文件的单项使用说明，可为空；与整份表单统一的 resource_usage 分开。', 'content_hash':'挂载时内容摘要快照，上传文件来自该文件版本 sha256。',
 'sort_order':'资源列表显示顺序；去掉的是技能大类表的排序字段，本字段仍保留。', 'created_time':'建立本版挂载关系的时间。',
 'skill_id':'所属技能编号，与 skill_version_id 通过复合外键校验归属；不是另一套版本正文。',
 'source_version_id':'固定使用的文件版本主键。不能自动跟随文件主表 current_version_id，避免历史构建被换版影响。'}),
'keenrobot_skill_debug_runs': ('我方调试版本关联', '当前业务', '只记录运行任务与实际技能版本/构建的关系及我方输入信息；运行状态、结果位置由同事维护。', '取得 run_id 后立即登记、重新打开核对版本、上线核对。', {
 'id':'我方关联记录主键，由后端生成；不同于同事 run_id。', 'run_id':'同事创建接口立即返回的任务唯一编号，本表唯一。',
 'skill_id':'这次任务调试哪个技能。', 'skill_version_id':'这次任务实际使用哪个已保存版本；登记后不能改绑。', 'build_id':'本次实际使用的构建编号，由对应版本核实并写入。',
 'conversation_input':'本次自然语言调试输入文本。', 'request_document_count':'临时输入文档数量（0～10）；我方不保存这些文档原件。',
 'resource_manifest_hash':'登记时复制对应版本的构建清单摘要，用于追溯。',
 'result_byte_size':'保留的旧结果大小字段；当前新登记代码不写，不用它判断调试成功。', 'error_code':'保留的旧错误码字段；当前新登记代码不写，真实失败原因读同事 error_message。',
 'created_by':'发起/登记任务的操作人平台编号，上线校验限定本人关联。', 'created_time':'首次关联时间；相同任务重复登记保持原关联。',
 'updated_time':'关联元数据时间；不是沙箱任务的 started_at 或 finished_at，也不是实时任务心跳。'}),
'keenrobot_skill_publications': ('上下线操作历史', '当前业务', '保留哪位操作者让哪一版上线或下线，不替代技能主表的当前状态。', 'publish / offline 与主表状态在同一事务内写入。', {
 'id':'操作记录主键。', 'skill_id':'操作的技能。', 'skill_version_id':'操作发生时的技能版本。', 'action':'PUBLISH 上线、OFFLINE 下线。',
 'operator_id':'操作者的平台编号。', 'reason':'预留操作原因；当前上下线请求没有原因参数，因此通常为空。', 'created_time':'操作发生时间。'}),
'keenrobot_online_debug_runs': ('同事沙箱运行结果', '同事维护，只读', '同事记录任务排队、运行、成功/失败、结果文档位置及过期时间。我方不会删改或要求其换表。', '同事四个任务接口读写；我方 SandboxResults 只读校验 run_id 与 skill_id、状态和过期时间。', {
 'id':'同事表内部自增主键；前端通常不用它。', 'skill_id':'任务所属技能标识，需要与我方技能稳定编号相同。', 'run_id':'对外任务唯一编号；我方用它关联，不使用此表自增 id。',
 'status':'同事协议为 queued / running / completed / failed。适配层将 completed 等成功值映射为 PASSED。',
 'result_file_path':'Excel 结果在同事服务端的文件路径；浏览器下载应调用 document 接口，不直接访问该路径。', 'result_file_name':'下载时使用的结果文件名。',
 'error_message':'执行失败原因，界面按实际错误显示。', 'started_at':'开始执行时间，排队时可以为空。', 'finished_at':'成功或失败结束时间，未结束为空。',
 'expires_at':'结果过期时间；上线校验不接受已过期的通过结果。'}),
'keenrobot_user': ('共享平台用户', '共享鉴权', '完整项目原有登录/公共鉴权依赖。之前删除后，按用户“恢复”授权从备份恢复；不是新增开发者中心用户系统。', '基础服务签发 Token、公共鉴权检查用户可用状态与 token_version；WRQ 不维护用户资料。', {
 'id':'共享平台用户编号，对应 JWT user_id。', 'username':'登录账号；由原平台接口维护。', 'password':'密码哈希，不能当作明文密码；本文不导出任何账号数据。',
 'alias':'显示名称/别名。', 'email':'邮箱。', 'phone':'联系电话。', 'motto':'个人简介/签名。', 'avatar':'头像地址或标识。',
 'is_active':'账号是否可用，公共鉴权要求为真。', 'is_superuser':'是否平台超级用户；WRQ 的本人编辑校验仍按创建人执行。',
 'last_login':'最近登录时间，原登录接口会更新。', 'token_version':'令牌版本；JWT 中版本与这里不一致即失效，用于吊销旧令牌。',
 'address':'联系地址。', 'gender':'性别代码，具体编码由共享平台约定，不由开发者中心重新定义。', 'user_type':'用户类型代码，由共享平台定义。',
 'emergency_name':'紧急联系人姓名。', 'emergency_phone':'紧急联系人电话。', 'state':'共享平台记录状态，公共鉴权排除已删除状态 1。',
 'created_time':'账号建立时间。', 'updated_time':'账号记录修改时间。', 'created_user':'创建该账号的人员标识。', 'updated_user':'最后修改人员标识。'}),
'keenrobot_audit': ('共享接口审计', '共享基础服务', '由原项目中间件记录请求和响应，开发者中心调用也可能产生审计记录。', '公共中间件追加审计，不是 Token 签发接口。', {
 'id':'审计记录主键。', 'created_user':'记录创建人员标识。', 'updated_user':'记录更新人员标识。', 'created_time':'审计行建立时间。', 'updated_time':'审计行更新时间。',
 'user_id':'本次接口调用人的用户编号。', 'username':'调用人用户名快照。', 'request_time':'请求到达时间。', 'request_tags':'接口所属模块/标签。', 'request_summary':'接口摘要。',
 'request_method':'HTTP 请求方法。', 'request_router':'请求路由。', 'request_client':'请求来源信息。', 'request_header':'请求头 JSON；当前公共日志存在敏感头记录，后续应脱敏。',
 'request_params':'请求参数文本；当前实现可能记录登录敏感参数，不能直接分享原始日志。', 'response_time':'响应生成时间。', 'response_header':'响应头 JSON。',
 'response_code':'应用响应代码。', 'response_message':'响应提示。', 'response_params':'响应内容文本；当前可能含令牌，需在公共审计模块另行脱敏。', 'response_elapsed':'响应耗时的字符串表示；单位以公共中间件实现为准。'}),
'aerich': ('迁移工具记录', '共享工具', '数据库迁移工具的历史元数据，不是业务表。自动迁移现已关闭。', '只有显式迁移工具使用；我方启动入口不会自动执行迁移。', {
 'id':'迁移记录自增主键。', 'version':'迁移版本/脚本标识。', 'app':'对应的 ORM 应用名称。', 'content':'迁移工具保存的模型结构 JSON，不是技能 config。'}),
'keenrobot_sources': ('历史旧资源实体', '历史保留，不走新流程', '旧设计遗留表。现行 Source 模型实际映射 uploaded_files；新接口不写本表。', '无现行开发者中心读写入口；暂未删除，不能按旧 COMMENT 当作当前用途结构。', {
 'id':'旧资源实体编号；不要拿它替代新上传接口返回的 sourceId。', 'source_type_id':'旧命名，历史上实际表示用途分类，COMMENT 仍引用已更名的 source_types；新代码使用 category_id 和 resource_categories。',
 'current_version_id':'旧方案的当前资源版本指针。现行文件主表也有同名字段，但归属不同，不应混用。', 'current_revision':'旧资源修订次数。',
 'created_by':'旧资源创建人的平台编号。', 'created_time':'旧资源记录建立时间。', 'updated_time':'旧记录更新时间。'}),
'keenrobot_skill_knowledge_bindings': ('历史独立知识库挂载', '历史保留，不走新流程', '旧版单独维护知识库关联；当前统一使用 skill_resource_bindings。', '模型名保留用于兼容导入；当前服务未向本表读写。', {
 'id':'旧关联主键。', 'skill_version_id':'旧记录关联的技能版本编号。', 'knowledge_base_id':'旧记录中的知识库编号。', 'knowledge_base_version':'旧记录中的知识库版本标记。'})
}

# method/path -> 页面用途、实际业务读写、关键约束/参数。公共鉴权与审计单列说明。
OPS = {}
def op(method, path, purpose, rw, rules, group='当前开发者中心'):
    OPS[(method, path)] = (purpose, rw, rules, group)

P='/skills/developer'
op('GET',P+'/context','取得当前调用人身份','WRQ 无业务表写入；完整项目外层读 user。','从已验证身份返回 id/name，不提供独立登录。')
op('GET',P+'/metadata','加载新建/编辑表单的选项','读 skill_classes、resource_categories；调用配置的门户目录（若有）。','返回 skill_classes/applications/resource_categories；旧响应键 source_types 只是用途的兼容别名。')
op('GET',P+'/','本人创建的技能列表','读 skills → versions/forms → resource_bindings/source_versions/resource_categories；有任务关联时读 debug_runs 与同事结果表。','只取 user_id=当前人、state=0；按更新时间倒序；data 是数组，不分页。')
op('POST',P+'/','创建草稿','同一事务写 skills + skill_versions + skill_forms + skill_resource_bindings；读取大类、用途、本人文件版本。','JSON DeveloperSkillForm；初始 revision=1、version=1.0.0、DRAFT；不信任前端创建者。')
op('PUT',P+'/{skill_id}','保存修改并新增技能版本','读/锁 skills；写新 versions/forms/resource_bindings；更新主表当前指针、名称、描述、状态。','expected_revision 必须等于当前修订；即使已上线，保存后也为 DRAFT、禁用并清当前通过标记。')
op('DELETE',P+'/{skill_id}','删除草稿','只更新 skills.state=1、is_enabled=false、updated_time；保留历史。','仅创建者且 DRAFT；二次确认在前端完成；删除后同名可再创建。')
op('POST',P+'/resources','持久化长期挂载文件','写 uploaded_files 与 source_versions；读 resource_categories；写服务器磁盘原件。','multipart files 多文件 + categories JSON字符串数组，顺序一一对应；用途中文或 code 均可；返回 sourceId/sourceVersionId。')
op('POST',P+'/resources/{source_id}/versions','保存同一文件的新版本','锁 uploaded_files，revision+1；新增 source_versions，更新文件当前属性与指针；旧版本不覆盖。','source_id 是文件实体 id；一次必须恰好一个文件，沿用 files + categories。')
op('GET',P+'/resources/{version_id}/download','下载某一版原件','读 source_versions 与 uploaded_files 做归属检查；读磁盘并校验 SHA256。','version_id 是文件版本 id；返回二进制文件；不是 result Excel，也不是 Skill ZIP。')
op('POST',P+'/{skill_id}/debug-runs','任务创建后立即登记实际技能版本','只读同事 online_debug_runs；读 versions；写我方 debug_runs，必要时更新 skills 当前版本任务/状态。','run_id 必填；build_id 或 skill_version_id 至少一个，传两者必须匹配；queued/running 就能登记；相同关联幂等，禁止改绑。')
op('GET',P+'/{skill_id}/debug-runs/{run_id}','恢复任务时核对是否为当前技能版本','读我方 skills/debug_runs/versions 与同事 online_debug_runs，不修改任务结果。','返回 run_id、skill_version_id、version、build_id、is_current_version、task；未登记返回 404。')
op('POST',P+'/{skill_id}/debug-result','旧登记接口兼容入口','与 POST debug-runs 完全相同的处理函数。','保留兼容；新前端使用 debug-runs；前端传 status=passed 不能作为通过证明。','兼容接口')
op('POST',P+'/{skill_id}/publish','核对当前版本调试通过后上线','读当前 versions、本人 debug_runs 关联和同事真实结果；事务更新 skills + 新增 publications。','只接受当前构建匹配且未过期的 PASSED；已 ONLINE 时幂等返回。可采纳当前版本任一次有效通过，不强制仅看最新任务。')
op('POST',P+'/{skill_id}/offline','将已上线技能下线','同一事务更新 skills=OFFLINE、is_enabled=false、offline_at；新增 publications。','只允许 ONLINE 下线；重复下线为业务错误。')
op('GET','/skills/name-availability','即时检查名称是否可用','读 skills 正常记录；有 exclude_id 时先校验本人技能。','query name 必填、最长128；exclude_id 编辑时排除自身；最终唯一性仍由数据库索引保证。')
op('POST','/skills/form/builds','从已保存版本构建 Skill 包','读/锁 skills、versions、forms、resource_bindings/source_versions/category；写 versions.build_id/package_storage_key/manifest_hash 与 forms.skill_markdown；写磁盘包。','multipart source=SkillDeveloperForm JSON字符串；expected_version 必须匹配，表单必须与已保存内容一致。实际文件读已保存文件版本；相同已构建版本验证后复用。')
op('GET','/skills/{skill_id}/definition','读取当前 SKILL.md','读 skills→versions/forms，核对已有构建磁盘内容。','当前版本未构建则返回业务不存在提示；此接口不会自动创建新版本。')
op('PUT','/skills/{skill_id}/definition','编辑 Markdown 并生成新版本/包','通过保存逻辑新增 versions/forms/bindings，更新 skills；随后构建新版本并保存构建元数据。','JSON markdown、expected_version；旧页面版本不匹配返回409。修改通过版本化保存，不覆盖旧构建。')
op('GET','/skills/{skill_id}/builds','查询构建历史目录','读本人技能权限与服务器构建目录；不是直接分页查 versions。','query limit=20（1～100）、offset=0；仅代表磁盘仍存在的构建。')
op('GET','/skills/{skill_id}/builds/{build_id}','读取构建清单和目录','读本人技能、磁盘 manifest/文件校验；查 versions 以补充版本编号。','path 为实际技能编号和构建编号。')
op('GET','/skills/{skill_id}/builds/{build_id}/download','下载完整 Skill ZIP','校验本人技能与构建目录/内容，读取磁盘 ZIP。','返回 application/zip；接口保留不等于页面必须显示“下载 Skill 包”按钮。')
op('POST','/skills/{skill_id}/validate','旧包源校验','读本人技能；使用旧资源合同解析已有知识库/文档。','JSON SkillPackageSource；不是创建草稿，也不登记调试版本；知识库相关表当前库未部署。','旧构建合同')
op('POST','/skills/{skill_id}/builds','旧 JSON 生成入口','读本人技能/旧资源数据，写构建磁盘文件；不走 build_form 的当前版本构建登记。','JSON SkillPackageSource；不应用于新的“构建→登记版本→上线”主流程。','旧构建合同')
op('POST','/skills/{skill_id}/builds/upload','旧统一文件上传构建','旧合同解析并写构建磁盘；不代替文件实体/版本上传接口。','multipart source=旧合同JSON + files；不作为当前前端入口。','旧构建合同')
op('POST','/skills/{skill_id}/builds/upload/entries','旧分参考资料/脚本构建','旧合同解析并写构建磁盘；不走当前版本完整保存链路。','multipart source + reference_files/script_files；仅兼容旧客户端。','旧构建合同')
op('GET','/skills/','旧 Agent 技能列表','读本人 skills，默认仅 ONLINE；补读 forms 映射旧 config 响应。','query manage=true 包括禁用项，search 模糊查名称；不是新的开发者完整表单列表。','旧 Agent 合同')
op('GET','/skills/{skill_id}','旧 Agent 技能查询','读本人 skills。','旧 SkillOut 形状，不含当前开发者中心全部表单字段。','旧 Agent 合同')
op('POST','/skills/','旧新增技能入口','不创建数据；服务拒绝该旧创建方式。','提示改用开发者中心完整表单；保留路由不代表旧合同仍能新增。','旧 Agent 合同')
op('PUT','/skills/{skill_id}','旧更新技能入口','不更新数据；服务拒绝该旧修改方式。','提示改用开发者中心完整表单保存；避免绕过版本化链路。','旧 Agent 合同')
op('DELETE','/skills/{skill_id}','旧草稿删除入口','委托现行 delete_draft，软删除 skills。','同样只允许本人草稿。','旧 Agent 合同')

SECTIONS=[]
def section(key,title,body):
    SECTIONS.append((key,title,body))

section('scope','1. 当前实现范围与结论',
 '<p>本文是 <strong>2026-10-26 当前实际实现说明</strong>，范围为开发者中心，以及它依赖的公共鉴权、文件存储、同事沙箱任务接口。依据运行中完整后端的 OpenAPI、WRQ 服务代码、云库只读结构快照和本轮测试报告整理；不是新一轮数据库重设计。</p>'+
 note(f'云库 <b>{esc(DB["database"])}</b>：16 张表、171 个字段；其中现行 WRQ 业务表 10 张、113 个字段。结构核对时间：{esc(DB["captured_at"])}。本次只读核对，未改表、未修改业务代码。')+
 table(['范围','当前事实'],[
 ['我们的代码',code('agent-template-master-latest/applications/wrq/')+'，负责表单、版本、长期文件、挂载、版本登记、上下线。'],
 ['同事代码/表','负责沙箱任务执行、运行状态和结果文档；'+code('keenrobot_online_debug_runs')+' 保留，由我方只读，<b>不再要求同事切表</b>。'],
 ['用户表','曾删除，后按“恢复”授权恢复 '+code('keenrobot_user')+'，供整个项目原鉴权使用。WRQ 没有另一套登录/用户资料维护。'],
 ['应用表','本地应用表未恢复；门户目录未配置时仅提供“全应用适用”。门户用户/应用正式接入仍待后续。'],
 ['不存在的旧设计',code('keenrobot_skill_debug_documents')+'、本地应用表、旧用途字典 '+code('keenrobot_source_types')+' 均不在当前库。'],
 ['实际保留','上下线历史表仍在使用；两张旧资源/知识库挂载表仍在库中但不走新流程，详见第7节。'],
 ['迁移','自动迁移关闭；本次文档生成不执行任何迁移或数据清理。']]))

section('architecture','2. 整体实现与职责',
 '<div class="flow"><span>前端表单/列表</span><b>→</b><span>WRQ 接口与事务</span><b>→</b><span>云 MySQL：技能、版本、文件关联</span></div>'+
 '<div class="flow"><span>前端运行调试</span><b>→</b><span>同事创建任务，立即返回 run_id</span><b>→</b><span>同事执行、保存状态与 Excel</span></div>'+
 '<div class="flow"><span>前端取得 run_id</span><b>→</b><span>我方登记 skill_version_id / build_id</span><b>→</b><span>上线时读取同事结果核实</span></div>'+
 table(['后端位置','职责'],[
 [code('applications/wrq/full_backend.py'),'启动 backend_main.app 的整个项目，保留公共路由/中间件，禁用启动自动迁移和初始化造数。'],
 [code('applications/wrq/auth.py'),'WRQ 内部 JWT 签名/有效期/身份校验；外层完整项目公共鉴权仍由 services/dependency.py 执行。'],
 [code('applications/wrq/agent/views/'),'当前开发者接口、定义与构建接口、旧 Agent 兼容入口。'],
 [code('applications/wrq/agent/services/developer_service_v2.py'),'本人权限、创建/修改事务、软删除、上下线、调试任务版本关联。developer_skill_crud.py 为兼容导入。'],
 [code('applications/wrq/agent/services/source_service.py'),'长期文件流式保存、文件版本、用途、受控原件下载与摘要验证。'],
 [code('applications/wrq/agent/services/skill_package_service.py'),'从已保存版本生成/复用构建、编辑定义、校验磁盘包。'],
 [code('applications/wrq/sandbox.py'),'只读同事结果表，校验任务属于该技能并转换状态；不启动模型。'],
 [code('applications/wrq/catalog.py'),'可选门户应用目录适配，无目录时返回系统选项 *。'],
 [code('applications/wrq/migrations/')+' / '+code('applications/wrq/tests/'),'显式迁移、备份、验证脚本与测试；不随服务启动自动执行。']]))

section('identity','3. Token、身份与应用目录',
 '<p>Token 的当前真实签发接口是 <code>POST /base/auth/access_token</code>，属于基础服务；<strong>审计模块只记录调用，不签发 Token</strong>。当前完整项目需要共享用户表，不能只保留 JWT 校验代码后就认定平台所有鉴权均已脱离用户表。</p>'+
 table(['接口/行为','参数与读取','说明'],[
 [code('POST /base/auth/access_token'),'JSON：username、password；读 user，验证密码哈希与状态，更新 last_login；公共中间件可能追加 audit。','使用真实平台账号；本文不包含账号密码或真实 Token。'],
 [code('POST /base/auth/userinfo'),'请求头 token；读取共享 user。','查看平台当前用户资料，不由开发者中心另建账号。'],
 ['完整项目受保护接口',code('token: <平台JWT>'),'验证签名/有效期，再查 user.id、is_active、state、token_version；WRQ 再按 user_id 校验本人记录。'],
 ['WRQ 内部校验','token 或 Bearer 解析为 PlatformIdentity。','完整项目外层目前要求 token 请求头，因此对整项目联调统一使用 token，不依赖仅 Bearer。'],
 ['门户应用适配',code('WRQ_PORTAL_APPLICATIONS_URL')+' 可选配置；期望列表包含 id/name。','尚未配置时不生成假应用清单。业务表只保存应用编号，不维护本地应用表。']])+
 '<p>将来接门户时，需要统一门户签发 Token 与整项目鉴权入口，再替换应用目录适配；这属于后续集成，并非当前已完成的身份同步。</p>')

section('ids','4. 编号、版本与来源/用途',
 table(['标识','在哪儿产生/保存','用一句话理解'],[
 [code('skill_id'),'skills.id；前端及同事四接口使用。','是哪一个技能。'],
 [code('skill_version_id'),'skill_versions.id，INT；调试关联记录保存。','这个技能保存的具体哪一版。'],
 [code('current_revision'),'skills 与 versions 中的技能内序号。','这是该技能的第几次保存；展示版本由它生成。'],
 [code('build_id'),'构建接口生成；写版本表。','这次实际生成/发送的哪一个 Skill 构建。'],
 [code('run_id'),'同事 POST runs 立即返回；我方 debug_runs 唯一记录。','这次沙箱执行任务的编号。'],
 [code('sourceId / file_id'),'uploaded_files.id。','同一份长期文件，换版后编号仍不变。'],
 [code('sourceVersionId / source_version_id'),'source_versions.id。','这份长期文件的确切哪一版。']])+
 note('例如：技能 A 的 revision=2、展示版本 1.0.1，但其版本主键可能是 87，因为其他技能也会消耗自增编号。current_version_id=87 只负责定位，不能算出 1.0.1。')+
 table(['概念','实际字段','内容及页面体现'],[
 ['来源：从哪里来',code('resource_bindings.source_type / source_id / source_version'),'upload：上传文件；knowledge_base：知识库；旧 knowledge_document 为兼容来源。通过上传/挂载入口区分，不是“用途”下拉框。'],
 ['用途：拿来做什么',code('uploaded_files.category_id')+' 与 '+code('source_versions.category_id')+' → '+code('resource_categories.id'),'reference 参考资料、template 模板、asset 静态资源、script 脚本；对应页面“用途”下拉框。'],
 ['历史旧命名','metadata.source_types、Python SourceType 别名、旧表 sources.source_type_id','前两项只是用途兼容命名；旧表列属于历史结构。新代码不把四种用途解释为来源。']])+
 '<p>例如上传 <code>信用卡字段字典.xlsx</code>，来源是 <code>upload</code>，用途是 <code>参考资料</code>，两者同时存在、不互相替代。当前没有另建“来源类型字典表”。</p>')

group_order=['当前开发者中心','兼容接口','旧构建合同','旧 Agent 合同']
body='<p>下表逐项对应运行中 OpenAPI 的全部 <code>/skills</code> 接口，共 30 个 HTTP 操作（同一路径不同方法分别计数）。表名为便于阅读省略 <code>keenrobot_</code> 前缀；“读写”列是业务操作，公共鉴权查用户、审计追加另按第3节理解。</p>'
for group in group_order:
    rows=[]
    for (method,path),(purpose,rw,rules,g) in OPS.items():
        if g!=group: continue
        rows.append([f'<span class="method">{method}</span> '+code(path),esc(purpose),esc(rw),esc(rules)])
    body+='<h3>'+esc(group)+'</h3>'+table(['方法与路径','用途','实际读写对象','请求与规则'],rows)
section('interfaces','5. 我方技能接口 → 数据库读写对照',body)

section('workflow','6. 调试联调与后续业务完整流程',
 '<h3>6.1 同事的四个接口：协议保持不变</h3>'+
 table(['接口','前端用途','数据库归属'],[
 [code('POST /realtime-test-case-gen/runs'),'创建后台任务，立即拿 run_id；multipart 目前沿用 skill_definition、skill_id、conversation_input、documents、mounted_resources。','同事负责 online_debug_runs；不要求他理解我方 skill_version_id/build_id。创建请求合同仍需真实服务联调确认。'],
 [code('GET /realtime-test-case-gen/runs/{run_id}'),'每5秒查询 queued/running/completed/failed、失败原因及时间。','同事维护状态，我方不复制这些状态到另一张结果表。'],
 [code('GET /realtime-test-case-gen/skills/{skill_id}/latest-run'),'重新打开调试窗口找最近任务。','只有技能编号不能证明是哪一版；还需查我方已保存的版本关联。'],
 [code('GET /realtime-test-case-gen/runs/{run_id}/document'),'completed 后下载 Excel；失败时保留原任务编号供查询重试。','结果在同事服务存储，浏览器通过接口下载。']])+
 '<h3>6.2 从创建到上线</h3><ol>'+''.join('<li>'+s+'</li>' for s in [
 '先保存技能草稿，获得技能 id、当前修订及版本 id。长期文件先通过我方资源上传接口保存，再把返回文件/版本编号写入表单。',
 '调用 <code>POST /skills/form/builds</code>，使用当前保存版本及其已固定的原件生成构建，取得 build_id 与 skill_version_id。',
 '前端冻结本次执行的版本和 build_id，再调用同事 <code>POST /runs</code>；不要在任务返回后读取已被用户改过的“当前版本”去替代原版本。',
 '收到 run_id 后立即调用我方 <code>POST /skills/developer/{skill_id}/debug-runs</code>。后端只读核对同事表中任务确实属于此技能，定位构建版本并登记。无需等待任务成功。',
 '同事后台继续执行；前端每5秒查询，关闭窗口停止当前页面查询但不取消后台任务。重新打开先 latest-run 找任务，再查我方关联是否属于当前版本。',
 '任务失败则显示同事 error_message；成功后下载 Excel。前端状态不直接作为上线凭证。',
 '点击上线时后端读取当前版本的本人关联，核对同事真实 PASSED、构建一致且结果未过期，事务保存 ONLINE 与上线历史。',
 '已上线技能一旦保存修改，产生新版本并回草稿。旧任务关联继续指向旧版本，不能用于新版上线。'])+'</ol>'+
 '<h3>6.3 立即登记到底写什么</h3><p>以下编号为说明用占位示例，不是真实数据库记录。</p>'+pre({'run_id':'同事刚返回的任务编号','build_id':'本次实际使用的构建编号','skill_version_id':87,'conversation_input':'生成登录场景测试用例','request_document_count':1})+
 '<p>后端在 <code>keenrobot_skill_debug_runs</code> 写入任务编号、技能编号、实际版本87、该版本构建编号、清单摘要和输入信息。运行状态仍在同事表。这里不是把任务结果复制一遍。</p>'+
 table(['场景','当前处理'],[
 ['同事还未让任务行可查询','登记返回409；保留原 run_id 重试，不再创建一个新沙箱任务。'],
 ['同一任务重复登记同一关联','幂等返回；不能换成另一技能、版本或用户。'],
 ['找回的是旧版本任务','可以显示其状态和结果，但 is_current_version=false，不能当作新版通过。'],
 ['找回未登记的历史任务','仅凭 run_id 无法补猜版本；只有保留原始构建/版本回执时才能重试登记。'],
 ['登记成功前浏览器突然彻底退出','两套服务的“创建任务”和“登记版本”不是一个跨服务事务。前端有短期回执和重试，但不能保证尚未取得/保存 run_id 的极端中断零丢失；后台任务本身仍继续。'],
 ['失败/成功同步','状态实时查询同事接口；我方后端登记/上线时读取同事表。当前没有新增结果回调或定时复制任务。']]))

ordered=['keenrobot_skills','keenrobot_skill_versions','keenrobot_skill_forms','keenrobot_skill_classes','keenrobot_resource_categories','keenrobot_skill_uploaded_files','keenrobot_source_versions','keenrobot_skill_resource_bindings','keenrobot_skill_debug_runs','keenrobot_skill_publications','keenrobot_online_debug_runs','keenrobot_user','keenrobot_audit','aerich','keenrobot_sources','keenrobot_skill_knowledge_bindings']
by_name={t['TABLE_NAME']:t for t in DB['tables']}
body='<p>以下完整列出当前云库16张表的171个字段。类型、可空、默认值和 COMMENT 来自数据库快照；“业务解释”依据现行代码补充。COMMENT 为空会如实标注，本文不假定全部共享/历史表均已按新方案修订。</p>'
body+=table(['表','字段数','归属/使用状态'],[[f'<a href="#db-{n}">{code(n)}</a> — '+INFO[n][0],len(by_name[n]['columns']),INFO[n][1]] for n in ordered])
for i,n in enumerate(ordered,1):
    t=by_name[n]; title,group,purpose,uses,explain=INFO[n]
    assert set(explain)=={c['COLUMN_NAME'] for c in t['columns']}, (n,set(explain)^{c['COLUMN_NAME'] for c in t['columns']})
    body+=f'<article class="db-table" id="db-{n}"><h3>7.{i} {code(n)} · {title}</h3><p><span class="tag">{group}</span> {purpose}</p><p><b>接口联系：</b>{uses}</p><p><b>云库表 COMMENT：</b>{esc(t["TABLE_COMMENT"] or "未设置")}</p>'
    rows=[]
    for c in t['columns']:
        field=c['COLUMN_NAME']
        attrs=('可空' if c['IS_NULLABLE']=='YES' else '非空') + ('；'+c['COLUMN_KEY'] if c['COLUMN_KEY'] else '')
        default='NULL/未设置' if c['COLUMN_DEFAULT'] is None else str(c['COLUMN_DEFAULT'])
        attrs+='；默认 '+default+('；'+c['EXTRA'] if c['EXTRA'] else '')
        rows.append([code(field),code(c['COLUMN_TYPE']),esc(attrs),esc(explain[field]),esc(c['COLUMN_COMMENT'] or '未设置')])
    body+=table(['字段','实际类型','可空/索引/默认','业务解释','实际 COLUMN COMMENT'],rows)
    refs=[r for r in DB['constraints'] if r['TABLE_NAME']==n and r['REFERENCED_TABLE_NAME']]
    if refs:
        body+='<details><summary>实际外键明细（复合外键按字段展示）</summary>'+table(['约束名','本表字段','目标表.字段'],[[code(r['CONSTRAINT_NAME']),code(r['COLUMN_NAME']),code(r['REFERENCED_TABLE_NAME']+'.'+r['REFERENCED_COLUMN_NAME'])] for r in refs])+'</details>'
    body+='<details><summary>只读查看当前实际建表定义（含索引与 CHECK，不是待执行迁移）</summary>'+pre(t['ddl'])+'</details></article>'
section('database','7. 每张表与全部字段说明',body)

section('consistency','8. 事务、一致性与状态规则',
 table(['规则','实际保障','边界'],[
 ['创建和保存','技能主表、版本、表单、挂载同一事务；修改时锁技能行并核对 expected_revision。','创建技能时没有历史版本可锁，由数据库名称唯一性和版本唯一性兜底。'],
 ['当前版本必须属于当前技能','复合外键：(skills.current_version_id, id, current_revision) → versions(id, skill_id, revision)。','current_version_id 不代替 current_revision，也不承担版本号计算。'],
 ['当前文件版本归属一致','文件当前指针与 file_id/revision 复合约束；挂载文件版本与 file_id 复合约束。','文件与文件版本仍保留主表当前属性/版本快照，是当前设计的有意保留。'],
 ['技能名称唯一且删除后可用','函数唯一索引只覆盖 state=0 的规范化名称；应用层还检查名称格式/可用性。','没有新增单独 name_key 业务列；软删除保留历史版本。'],
 ['状态与启用一致','数据库 CHECK：ONLINE ↔ is_enabled=true；其他状态均禁用；上下线历史同事务写。','DEBUGGING 是技能业务状态，不是同事 task.status 的逐项镜像。'],
 ['保存修改不能复用旧测试','revision+1、新 versions/forms/bindings、DRAFT、禁用，清当前任务/通过标记。','历史构建与关联保留，用于追溯。'],
 ['运行任务关联固定','run_id 唯一，登记时核对技能/构建归属；同一关联幂等，跨版本改绑返回409。','跨我方与同事任务创建无分布式事务；登记失败重试原 run_id。'],
 ['上线相信后端真实结果','只读同事任务结果，版本与构建一致且 PASSED、未过期才可上线。','如果当前版本以前有一次有效通过，即使较新一次失败，现行逻辑仍可采纳该有效通过；不等同于“只允许最新一次通过”。'],
 ['文件内容不静默变化','保存真实大小和摘要，下载/构建时校验受控路径与 SHA256；换版新增原件位置。','校验后缀和路径不等于完整病毒扫描或所有文件内容解析。'],
 ['文件系统与数据库事务','上传失败会清理本次临时原件，构建失败清本次构建目录，数据库事务回滚。','进程/机器崩溃不具备跨文件系统原子事务，部署仍需存储备份与孤儿文件巡检。']])+
 '<h3>常见状态变化</h3>'+table(['动作','结果'],[['新建','DRAFT / 禁用 / 1.0.0'],['首次构建或当前版本登记任务','DRAFT → DEBUGGING；构建与任务执行是两个动作。'],['调试成功','同事任务 completed；技能不会自动上线。'],['上线校验通过','ONLINE / 启用，记 publications。'],['已上线保存修改','新版本 DRAFT / 禁用，旧通过不能给新版用。'],['下线','ONLINE → OFFLINE / 禁用，记 publications。'],['删除草稿','state=1，默认本人列表不再展示，名称释放。']]))

FORM_DESC={
'expected_revision':'创建时可不传；修改时业务必填，必须等于当前 current_revision，防旧页面覆盖。',
'name':'技能名称→主表当前副本及 forms.name；1～128字符，另有名称格式校验。',
'class_id':'大类编号→forms.skill_class_id；必须是启用的大类。',
'application_ids':'当前只接受0或1个应用编号→forms.application_id；* 全应用适用。后端目前允许空数组，并非强制至少一个。',
'description':'描述→forms.description 与 skills.description 查询副本；1～1024字符。',
'instructions':'执行指令→forms.instructions；1～100000字符。',
'resource_ids':'知识库编号列表→resource_bindings 的 knowledge_base 来源；当前库缺少知识库业务表，见待完成项。',
'resource_usage':'统一资源使用说明→forms.resource_usage；有挂载时必填，最长10000。',
'compatibility':'可选运行环境要求→forms.compatibility，最长500。',
'technical_name':'技术名→forms.technical_name；不填由后端生成，最长128。',
'uploaded_resources':'资源上传返回的元数据对象数组；实际校验 sourceId、sourceVersionId、category，不能只传浏览器文件名。',
'knowledge_bases':'兼容页面展示对象；真实挂载验证以 resource_ids 为准。',
'skill_markdown':'普通表单中保留兼容字段；真正编辑定义走 PUT definition，不能靠普通保存任意覆盖。',
'run_id':'同事返回的任务编号；登记接口必填，最长128；同事现表 run_id 长度32。',
'build_id':'实际使用构建；与 skill_version_id 至少传一个，后端查已保存版本核实，推荐传构建且同时带版本。',
'skill_version_id':'实际使用版本整数主键；若同时传 build_id，二者必须定位同一版。',
'status':'旧请求兼容字段；不信任它来认定通过，也不把它复制为另一张结果表的状态。',
'conversation_input':'本次调试自然语言文本，保存到我方关联表，最长100000。',
'request_document_count':'本次临时输入文档数，0～10；不是文件原件保存。',
'result_file_name':'旧请求兼容字段；当前新登记不写入，结果名读同事结果。',
'result_byte_size':'旧请求兼容字段；当前新登记不写入。',
'error_message':'旧请求兼容字段；真实失败原因读同事结果，不能由浏览器伪造。',
}
body='<p>接口使用两种表单合同：创建/保存草稿使用 DeveloperSkillForm；生成包使用 SkillDeveloperForm（multipart source 字符串）。它们的字段名不能混用。</p>'
for name in ['DeveloperSkillForm','DeveloperDebugResult','SkillDeveloperForm','SkillDefinitionEdit']:
    s=SkillDeveloperForm.model_json_schema() if name=='SkillDeveloperForm' else API['components']['schemas'][name]
    rows=[]
    for field,p in s['properties'].items():
        limit=[]
        variants=p.get('anyOf',[p])
        for v in variants:
            for k in ('minLength','maxLength','minimum','maximum','maxItems'):
                if k in v: limit.append(k+'='+str(v[k]))
        typ=p.get('type',' / '.join(v.get('type','对象') for v in variants))
        desc=FORM_DESC.get(field,p.get('description') or {
          'skill_id':'已保存技能编号，用于定位当前技能；不是允许客户端指定创建者。',
          'skill_name':'必须与已保存 forms.name 一致。', 'version':'展示版本输入；实际构建使用已保存版本。',
          'skill_class_id':'必须与已保存 forms.skill_class_id 一致。', 'application':'必须与已保存 forms.application_id 一致。',
          'resource_categories':'兼容表单项；实际构建按已保存文件版本 category_id 取得用途，不信任客户端替换。',
          'expected_version':'必须等于当前已保存展示版本，如 1.0.0；过期返回409。',
          'knowledge_base_ids':'知识库来源选择，仍需实际知识库权限和原文件解析支撑。',
          'markdown':'编辑后的 Markdown，非空且最长200000字符；保存将新增版本并重新构建。'}.get(field,'见当前 OpenAPI 请求合同。'))
        if name=='SkillDeveloperForm' and field=='skill_markdown': desc='构建实际使用已保存表单内容，不允许这个输入绕过版本保存。'
        rows.append([code(field),esc(typ),('Schema必填' if field in s.get('required',[]) else 'Schema可省略')+('<br>'+esc('；'.join(limit)) if limit else ''),esc(desc)])
    body+='<h3>'+name+'</h3>'+table(['字段','类型','Schema要求/长度','含义及业务要求'],rows)
body+='<p>资源对象示例（占位数据）：</p>'+pre({'sourceId':12,'sourceVersionId':31,'category':'参考资料','usage':'核对字段定义'})
body+='<h3>当前技能列表/创建/保存响应的字段落点</h3><p>创建、保存、登记、上线和下线成功后，通常返回同一种技能详情对象；本人列表的 data 是该对象的数组。下表帮助把页面字段与数据库对应起来。</p>'+table(['响应字段','数据库来源或计算','说明'],[
 [code('id / backend_skill_id'),code('skills.id'),'同一个稳定技能编号的页面兼容别名。'],
 [code('name / description / instructions / resource_usage / compatibility / technical_name / skill_markdown'),code('当前 skill_forms 同名字段'),'读取当前版本正文；普通页面不会混用旧版本表单。'],
 [code('class_id'),code('skill_forms.skill_class_id'),'选项名称通过 metadata 大类字典显示。'],
 [code('application_ids'),code('skill_forms.application_id'),'单个数据库值包装为数组；为空则空数组。'],
 [code('version / current_revision / skill_version_id'),code('skill_versions.version / revision / id'),'分别是展示版本、技能内修订和整数主键，不能互换。'],
 [code('status'),code('skills.display_status')+' 映射中文','返回草稿/调试中/已上线/已下线；不是同事任务 status。'],
 [code('creator_id / creator_name'),code('skills.user_id')+' / 当前身份显示名','本人接口的创建者编号来自数据库；显示名来自已验证身份，不是另建本地演示账号。'],
 [code('updated_at'),code('skills.updated_time'),'用于前端更新时间显示。'],
 [code('build_id / build_origin'),code('skill_versions.build_id')+' / 派生标记','有构建时 build_origin=backend；未构建为空。'],
 [code('uploaded_resources'),'读 resource_bindings 固定的 source_versions + category字典','包含 sourceId、sourceVersionId、name、size、category、downloadUrl、usage；原件版本固定。'],
 [code('resource_ids / knowledge_bases'),'knowledge_base 来源的 resource_bindings','知识库编号数组及显示对象；真实知识库业务仍受第12节部署限制。'],
 [code('debug'),'当前版本最近一条我方 debug_runs + 同事真实结果','可含 id/runId/buildId/skillVersionId/status/output/origin；成功状态经适配后可能为 passed，而同事原接口为 completed。不存在有效关联/结果则为空。']])
body+='<h3>任务关联查询的返回值</h3>'+pre({'run_id':'同事任务编号','skill_id':'技能编号','skill_version_id':87,'version':'1.0.1','build_id':'执行时构建编号','is_current_version':False,'task':{'run_id':'同事任务编号','skill_id':'技能编号','status':'RUNNING','result_file_path':None,'result_file_name':None,'error_message':None,'expires_at':None,'started_at':'示例时间','finished_at':None}})+'<p>task 来自只读适配层，状态为大写规范值；is_current_version 才是界面判断旧任务是否可代表当前版本的依据，任务编号本身不能说明版本。</p>'
section('payloads','9. 请求字段与数据库落点',body)

section('errors','10. 错误响应与前端处理',
 '<p>WRQ 路由通过 WrqRoute 将 DeveloperError 转为对应 HTTP 状态，统一包含 code、status、message、data；字段错误放在 data.errors。成功响应沿用公共 SuccessResponse，列表额外有 total。</p>'+
 pre({'code':409,'status':'failure','message':'技能已被修改或缺少版本信息，请刷新后重试','data':None})+
 table(['情况','当前处理'],[['业务参数错误','一般400；错误原因在 message / data.errors。'],['无记录或无权操作','WRQ 服务统一404，避免给出可编辑的他人对象。'],['版本冲突/任务改绑/未通过上线','409；刷新当前版本或用原 run_id 重试登记，不创建重复任务。'],['Pydantic请求格式错误','WRQ 路由422，携带字段路径。'],['未处理异常','WRQ 路由500；对外通用消息，详细原因在后端日志。'],['原项目全局鉴权/部分兼容包装','可能 HTTP200 但业务 status=failure，例如 code=400401；构建 ParameterResponse 也可能HTTP200。因此客户端必须同时检查 HTTP 和业务 status/code。']])+
 '<p>不能把“HTTP200”单独当作成功，也不能把浏览器传回的 passed 当作模型执行证明。</p>')

section('storage','11. 格式、大小、存储和 TLS',
 table(['内容','实际规则'],[
 ['长期资源格式','.py / .js / .md / .xlsx / .docx / .png / .jpg / .jpeg；由后端 resource_role 校验，拒绝路径型文件名。'],
 ['沙箱临时输入格式','与长期资源不同：前端按 PDF / Word / Markdown / TXT / Excel / JSON 校验。临时原件交给同事，不写我方长期文件表。其后端限制需同事服务真实联调核实。'],
 ['大小','长期资源后端单文件及一次总量均为50×1024×1024字节；保存技能时也核对所挂上传文件总量。前端沙箱输入沿用50MiB单文件/总量限制。'],
 ['数量','长期资源上传防异常 multipart 上限100个；我方调试登记文档数量0～10。不同入口的数量要求不混为一谈。'],
 ['原件和包','原件、构建目录、ZIP 当前放在 SKILL_BUILD_DIR 的服务器磁盘；MySQL保存路径/摘要/关联，不直接保存全部文件字节。'],
 ['多机协作','共享云数据库并不会共享各电脑磁盘。当前前端可下载本人固定原件后传同事；正式部署仍要约定统一存储或文件传输与备份。'],
 ['数据库TLS','通过 asyncmy 的 ssl.SSLContext 建立加密连接；核对到 '+esc(DB['tls_cipher'])+'。密码仅在私有配置读取，本文不展示。'],
 ['证书校验现状','当前 DATABASE_SSL_CA 未配置：连接有加密，但代码关闭了 CA/主机名身份验证；不能描述成已完成服务器证书身份认证。提供CA后应启用验证。'],
 ['自动迁移',code('DATABASE_AUTO_MIGRATION=false')+'；完整启动入口拒绝在自动迁移开启时运行。显式迁移须备份且不能改同事表。']]))

passed=sum(c.get('result')=='passed' or c.get('status')=='passed' for c in TEST['cases'])
status_values={str(c.get('status',c.get('result'))) for c in TEST['cases']}
section('tests','12. 已完成验证与未完成项',
 '<h3>已有测试证据</h3>'+bullets([
 '本轮调试后续链路用例 <b>37项全部通过</b>；沙箱任务状态和Excel为Mock，JWT、HTTP、真实云MySQL、构建、版本登记、上下线等实际执行。',
 '前端 <b>42项测试通过</b>，生产构建通过；使用实际API函数做TCP联调，Node内仅浏览器缓存使用测试存储。没有据此声称完成浏览器UI刷新验收。',
 '恢复共享用户后，完整项目原签发Token接口与受保护开发者接口实际验证通过；无Token请求被拒绝。',
 '本次文档额外只读核对云库16表171字段与运行中OpenAPI，不重复修改数据或执行迁移。'])+
 '<p><a href="开发者中心_调试后续流程测试用例_20261026.html">查看37项用例</a> · <a href="开发者中心_调试后续流程测试结果_20261026.html">查看测试结果</a> · <a href="用户表恢复与整项目鉴权验证_20261026.json">查看整项目鉴权证据</a></p>'+
 '<h3>尚不能算完成的内容</h3>'+table(['项目','现状与下一步'],[
 ['同事真实沙箱联调','目前配置目标服务不可达；真实模型执行、任务响应与Excel下载未通过实机联调。前端四接口流程已接好，但创建multipart合同仍需对照同事真实服务验证。'],
 ['门户用户/应用','当前用恢复的共享用户表鉴权；没有完成门户用户同步/统一认证改造。应用目录未配置时仅系统全应用选项。'],
 ['知识库挂载全链路','当前云库未部署知识库实体/文档等表。挂载校验代码存在，但不能声称知识库解析/历史版本/向量索引均已实现；知识库 revision 缺失时默认1也不是真正版本存储。'],
 ['旧资源结构清理','sources 与 skill_knowledge_bindings 不再走当前读写但仍在云库；其COMMENT不等于现行规范。是否清理应单独制定数据核对，不在本文执行。'],
 ['公共表注释','现行10张业务表表/字段COMMENT齐全；共享 user 与 aerich 未设置COMMENT，audit没有表级COMMENT。此处如实记录，未擅自改共享模块。'],
 ['公共审计脱敏','现有公共中间件会记录请求/响应敏感内容；Token、登录密码等仍需在公共审计/日志层统一脱敏。本文不导出原始审计数据。'],
 ['共享文件存储','目前本机磁盘路径不是跨机器共享存储；部署前需统一原件/构建存储和备份。'],
 ['极端中断与跨服务原子性','先创建任务再登记关联存在时间窗；当前前端回执重试降低风险，没有宣称两服务已经原子提交。']]))

section('run','13. 启动、调用和交接方式',
 '<p>在后端根目录 <code>agent-template-master-latest</code> 执行：</p>'+pre('.\\.venv\\Scripts\\python.exe -m applications.wrq.full_backend')+
 '<p>完整后端文档：<a href="http://127.0.0.1:8519/docs">http://127.0.0.1:8519/docs</a>；前端：<a href="http://127.0.0.1:5175/">http://127.0.0.1:5175/</a>。OpenAPI路径为 <code>/openapi_url</code>。本机端口是当前联调配置，部署环境可不同。</p>'+
 '<ol><li>用原基础服务账号调用 access_token，取得Token；不要从审计记录复制他人凭证。</li><li>受保护请求统一携带 <code>token: &lt;平台JWT&gt;</code>。</li><li>先调用 context、metadata 和本人列表，再创建/保存完整表单。</li><li>按第6节执行构建、同事创建、立即登记、查询/恢复、下载、上线和修改回草稿。</li></ol>'+
 note('交接给同事的要求保持简单：skill_id 使用同一技能编号；创建任务立即返回 run_id；四个接口按约定可用。我方独立负责 run_id 与技能版本关联；不要求对方新增我方表单字段、不改他的任务表。')+
 '<p>证据文件：<a href="开发者中心_最终后端_数据库结构快照_20261026.json">只读数据库结构快照</a>、<a href="开发者中心_最终后端_OpenAPI快照_20261026.json">完整项目OpenAPI快照</a>。结构快照不含用户、审计或技能业务行数据；完整OpenAPI中其余模块仅代表路由已加载，不代表它们已完成本轮数据库与功能验收。</p>')

def validate():
    actual={(m.upper(),p) for p,ops in API['paths'].items() if p.startswith('/skills') for m in ops if m in ['get','post','put','delete','patch']}
    assert actual==set(OPS), ('API coverage mismatch',actual-set(OPS),set(OPS)-actual)
    assert set(INFO)==set(by_name)
    assert sum(len(t['columns']) for t in DB['tables'])==171
    assert len(TEST['cases'])==37
    # Test report case status uses Chinese labels in some historical formats.
    statuses=[c.get('status', c.get('result')) for c in TEST['cases']]
    assert all(s in ('PASSED','passed','通过','PASS','pass') for s in statuses), statuses
    assert all(t['TABLE_COMMENT'] and all(c['COLUMN_COMMENT'] for c in t['columns']) for t in DB['tables'] if INFO[t['TABLE_NAME']][1]=='当前业务')

CSS='''
:root{--ink:#172b45;--muted:#61738c;--blue:#1760bb;--line:#dce5ef;--bg:#f3f6fa}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--bg);font:15px/1.8 "Microsoft YaHei",system-ui,sans-serif}
aside{position:fixed;inset:0 auto 0 0;width:248px;background:#10243e;color:white;overflow:auto;padding:26px 20px}aside strong{font-size:20px}aside a{display:block;color:#c4d7f1;text-decoration:none;padding:7px 0;font-size:13px;line-height:1.5}aside a:hover{color:#fff}
main{margin-left:248px;padding:32px 36px;max-width:1800px}header{padding:22px 28px;border-radius:14px;background:#173d6a;color:#fff}header p{color:#d5e1f3}h1{font-size:29px;margin:4px 0}h2{font-size:23px;border-bottom:2px solid var(--line);padding-bottom:10px}h3{font-size:18px;margin-top:27px}section{background:#fff;padding:24px 28px;border:1px solid var(--line);border-radius:12px;margin:22px 0;scroll-margin-top:15px}p{margin:12px 0}a{color:var(--blue)}.note{padding:15px 18px;border-left:4px solid #3d81cc;background:#eef5ff;margin:16px 0;border-radius:4px}.flow{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:16px 0}.flow span{border:1px solid #b8d0e9;background:#f5f9ff;border-radius:7px;padding:12px 16px}.flow b{color:#5c86b1}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.7}th,td{border:1px solid var(--line);text-align:left;vertical-align:top;padding:10px 12px}th{background:#edf3fa;color:#23466d}tr:nth-child(even){background:#fafcfe}td{overflow-wrap:anywhere}code{font:13px/1.6 Consolas,"Microsoft YaHei",monospace;background:#edf2f7;border-radius:4px;padding:2px 4px;overflow-wrap:anywhere}pre{background:#10243e;color:#e1edfc;padding:18px;border-radius:8px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:13px/1.65 Consolas,"Microsoft YaHei",monospace}.scroll{overflow:auto;margin:14px 0}.tag{display:inline-block;background:#e5f2ed;color:#24664b;padding:2px 9px;border-radius:20px;font-size:12px}.method{font-weight:bold;color:#1760bb}.db-table{scroll-margin-top:15px;padding-top:4px}.db-table table{min-width:900px}.db-table th:nth-child(1){width:13%}.db-table th:nth-child(2){width:12%}.db-table th:nth-child(3){width:17%}.db-table th:nth-child(4){width:39%}.db-table th:nth-child(5){width:19%}details{margin:12px 0}summary{cursor:pointer;color:var(--blue)}input{width:100%;padding:10px 12px;font:14px "Microsoft YaHei";border-radius:7px;border:1px solid #94b1d2;margin-top:14px}footer{padding:20px;color:var(--muted)}button{cursor:pointer;border:1px solid #bdd0e6;color:#23466d;background:#f5f9ff;border-radius:6px;padding:8px 12px;margin-right:8px}
@media(max-width:1000px){aside{position:static;width:auto}aside nav{display:flex;flex-wrap:wrap;gap:12px}main{margin:0;padding:14px}section{padding:16px}header{padding:18px}h1{font-size:24px}}
@media print{body{background:#fff;font-size:10pt}aside,.tools{display:none}main{margin:0;padding:0;max-width:none}section{border:0;margin:10pt 0;padding:0;break-before:page}section:first-of-type{break-before:auto}header{background:#fff;color:#172b45;padding:0}header p{color:#61738c}table{font-size:8pt}thead{display:table-header-group}tr{break-inside:avoid}h2,h3{break-after:avoid}pre{background:#f3f6fa;color:#172b45}.scroll{overflow:visible}.db-table table{min-width:0}details[open] pre{font-size:7pt}a{color:#172b45;text-decoration:none}}
'''

def main():
    validate()
    toc=''.join(f'<a href="#{key}">{esc(title)}</a>' for key,title,_ in SECTIONS)
    body=''.join(f'<section id="{key}"><h2>{esc(title)}</h2>{content}</section>' for key,title,content in SECTIONS)
    content='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>开发者中心 · 最终后端实现方案与接口数据库说明</title><style>'+CSS+'</style></head><body><aside><strong>开发者中心</strong><p>最终后端实现说明<br>2026-10-26</p><nav>'+toc+'</nav></aside><main><header><h1>最终后端实现方案与接口、数据库说明</h1><p>实际代码 × 运行中 OpenAPI × 云数据库结构 · 30个我方技能操作 + 2个鉴权接口 + 4个同事任务接口 · 16张表 / 171个字段</p></header><div class="tools"><input id="find" placeholder="搜索字段或接口，例如 category_id、debug-runs（也可 Ctrl+F 全文查找）"><p><button onclick="window.print()">打印 / 另存PDF</button><button onclick="document.querySelectorAll(\'details\').forEach(x=>x.open=true)">展开结构明细</button></p><div id="hits"></div></div>'+body+'<footer>本文记录当前实现，不执行数据库迁移。生成程序位于 applications/wrq/docs/build_final_reference_20261026.py；数据库与OpenAPI快照为只读证据。</footer></main><script>const f=document.querySelector("#find"),h=document.querySelector("#hits");f.addEventListener("input",()=>{const q=f.value.trim().toLowerCase();h.replaceChildren();if(!q)return;for(const a of document.querySelectorAll(".db-table,section")){if(!a.textContent.toLowerCase().includes(q))continue;if(a.tagName==="SECTION"&&a.id==="database")continue;const link=document.createElement("a");link.href="#"+a.id;link.textContent=a.querySelector("h2,h3").textContent;link.style.display="block";h.append(link);}});</script></body></html>'
    path=OUT/'开发者中心_最终后端实现方案与接口数据库说明_20261026.html'
    path.write_text(content,encoding='utf8')
    print(json.dumps({'document':str(path),'tables':len(DB['tables']),'fields':171,'skill_http_operations':len(OPS),'sections':len(SECTIONS),'bytes':path.stat().st_size},ensure_ascii=False))

if __name__=='__main__':
    main()
