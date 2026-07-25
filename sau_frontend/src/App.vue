<template>
  <div v-if="!user" class="login-page">
    <div class="login-panel">
      <div class="brand-mark">小羊</div>
      <h1>视频全自动分发</h1>
      <p>面向团队运营的多平台视频发布系统</p>
      <el-form @submit.prevent="doLogin" size="large">
        <el-form-item><el-input v-model="loginForm.username" placeholder="用户名" prefix-icon="User" /></el-form-item>
        <el-form-item><el-input v-model="loginForm.password" type="password" show-password placeholder="密码" prefix-icon="Lock" @keyup.enter="doLogin" /></el-form-item>
        <el-button type="primary" class="login-button" :loading="loading" @click="doLogin">安全登录</el-button>
      </el-form>
    </div>
  </div>

  <el-container v-else class="shell">
    <el-aside width="232px" class="sidebar">
      <div class="brand"><span class="brand-mark small">视频</span><div><b>视频全自动分发</b><small>多平台发布控制台</small></div></div>
      <el-menu :default-active="page" @select="selectPage">
        <el-menu-item index="dashboard"><el-icon><DataBoard /></el-icon>工作台</el-menu-item>
        <el-menu-item index="publish"><el-icon><Promotion /></el-icon>新建发布</el-menu-item>
        <el-menu-item index="jobs"><el-icon><List /></el-icon>发布记录</el-menu-item>
        <el-menu-item index="materials"><el-icon><VideoCamera /></el-icon>素材库</el-menu-item>
        <el-menu-item index="accounts"><el-icon><Connection /></el-icon>平台账号</el-menu-item>
        <el-menu-item v-if="isAdmin" index="users"><el-icon><UserFilled /></el-icon>员工管理</el-menu-item>
        <el-menu-item v-if="isAdmin" index="audit"><el-icon><Document /></el-icon>操作日志</el-menu-item>
      </el-menu>
      <div class="sidebar-user">
        <el-avatar>{{ user.display_name.slice(0, 1) }}</el-avatar>
        <div><b>{{ user.display_name }}</b><small>{{ isAdmin ? '管理员' : '操作员' }}</small></div>
        <el-button text circle @click="logout"><el-icon><SwitchButton /></el-icon></el-button>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar"><div><span class="eyebrow">SOCIAL AUTO UPLOAD</span><h2>{{ pageTitle }}</h2></div><el-button @click="refresh"><el-icon><Refresh /></el-icon>刷新</el-button></el-header>
      <el-main>
        <template v-if="page === 'dashboard'">
          <div class="hero"><div><span class="pill">运行正常</span><h1>你好，{{ user.display_name }}</h1><p>统一管理素材、平台账号与跨平台发布任务。</p></div><el-button type="primary" size="large" @click="selectPage('publish')">创建发布任务</el-button></div>
          <div class="stats">
            <div class="stat"><span>可用账号</span><strong>{{ stats.accounts || 0 }}</strong><small>个发布目标</small></div>
            <div class="stat"><span>视频素材</span><strong>{{ stats.materials || 0 }}</strong><small>个已上传文件</small></div>
            <div class="stat"><span>发布任务</span><strong>{{ stats.jobs || 0 }}</strong><small>个任务批次</small></div>
            <div class="stat accent"><span>成功发布</span><strong>{{ stats.success || 0 }}</strong><small>个平台任务</small></div>
          </div>
          <section class="panel"><div class="section-head"><div><span class="eyebrow">RECENT ACTIVITY</span><h3>最近发布</h3></div></div><job-table :jobs="jobs.slice(0, 6)" /></section>
        </template>

        <template v-else-if="page === 'publish'">
          <section class="panel publish-panel">
            <div class="section-head"><div><span class="eyebrow">NEW DELIVERY</span><h3>创建多平台发布任务</h3><p>依次选择素材、发布平台和平台账号；没有账号时可在这里直接添加。</p></div></div>
            <el-form label-position="top" class="publish-form">
              <div class="two-col"><el-form-item label="视频素材（必选）"><div class="material-select"><el-select v-model="publish.material_id" placeholder="选择已上传素材" filterable><el-option v-for="m in materials" :key="m.id" :label="m.original_name" :value="m.id" /></el-select><el-upload :show-file-list="false" :http-request="uploadAndSelectMaterial" accept="video/mp4,video/quicktime,video/x-matroska,video/webm"><el-button type="primary" plain :loading="uploading"><el-icon><Upload /></el-icon>选择本地视频</el-button></el-upload></div><el-alert v-if="analysisLoading" class="analysis-status" title="正在识别视频语音并生成标题、简介和标签，请稍候…" type="info" :closable="false" show-icon /><el-button v-else class="analyze-button" type="success" plain :disabled="!publish.material_id" @click="analyzeMaterial(true)">重新提取内容</el-button><small class="field-tip">上传或选择素材后会自动提取；生成结果可继续修改。</small></el-form-item><el-form-item label="发布时间（可选）"><el-date-picker v-model="publish.schedule_at" type="datetime" value-format="YYYY-MM-DDTHH:mm" placeholder="立即发布" /></el-form-item></div>
              <el-form-item label="发布平台（必选）"><el-checkbox-group v-model="publish.platforms" class="platform-picker"><el-checkbox v-for="p in availablePlatforms" :key="p.value" :value="p.value" border><span class="platform-dot" :class="p.value"></span>{{ p.label }}</el-checkbox></el-checkbox-group></el-form-item>
              <el-form-item label="平台账号（必选）"><div class="account-heading"><span>请选择上述平台对应的发布账号</span><el-button v-if="isAdmin" type="primary" plain @click="openAccountFromPublish"><el-icon><Plus /></el-icon>添加平台账号</el-button></div><el-checkbox-group v-if="filteredPublishAccounts.length" v-model="publish.account_ids" class="account-picker"><el-checkbox v-for="a in filteredPublishAccounts" :key="a.id" :value="a.id" border><span class="platform-dot" :class="a.platform"></span>{{ platformName(a.platform) }} · {{ a.display_name }} <el-tag size="small" :type="a.status === 'ready' ? 'success' : 'warning'">{{ statusName(a.status) }}</el-tag></el-checkbox></el-checkbox-group><el-empty v-else :description="publish.platforms.length ? '所选平台暂无账号，请点击添加平台账号' : '请先选择发布平台'" :image-size="72" /></el-form-item>
              <el-form-item label="标题"><el-input v-model="publish.title" maxlength="100" show-word-limit placeholder="输入统一标题" /></el-form-item>
              <el-form-item label="简介"><el-input v-model="publish.description" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="输入视频简介" /></el-form-item>
              <el-form-item label="标签"><el-input v-model="publish.tags" placeholder="多个标签用英文逗号分隔，例如：科技,健康,科普" /></el-form-item>
              <div class="form-actions"><el-button type="primary" size="large" :loading="loading" @click="createJob">提交发布任务</el-button></div>
            </el-form>
          </section>
        </template>

        <template v-else-if="page === 'jobs'">
          <section class="panel"><div class="section-head"><div><span class="eyebrow">DELIVERY HISTORY</span><h3>发布记录</h3><p>失败任务可查看原因并直接重试，不会重复发布已成功的平台。</p></div></div><job-table :jobs="jobs" @retry="retryJob" /></section>
        </template>

        <template v-else-if="page === 'materials'">
          <section class="panel"><div class="section-head"><div><span class="eyebrow">MEDIA LIBRARY</span><h3>视频素材</h3><p>上传后所有授权同事均可在发布中心选择。</p></div><el-upload :show-file-list="false" :http-request="uploadMaterial" accept="video/*"><el-button type="primary"><el-icon><Upload /></el-icon>上传视频</el-button></el-upload></div>
            <el-table :data="materials"><el-table-column prop="original_name" label="文件名" min-width="260" /><el-table-column label="发布状态" width="145"><template #default="s"><el-tag :type="materialPublishType(s.row.publish_status)">{{ materialPublishName(s.row.publish_status) }}</el-tag></template></el-table-column><el-table-column label="智能内容" width="120"><template #default="s"><el-tag :type="s.row.analysis_title ? 'success' : 'info'">{{ s.row.analysis_title ? '已提取' : '未提取' }}</el-tag></template></el-table-column><el-table-column label="大小" width="110"><template #default="s">{{ formatSize(s.row.size_bytes) }}</template></el-table-column><el-table-column prop="uploader" label="上传人" width="120" /><el-table-column label="上传时间" width="180"><template #default="s">{{ formatTime(s.row.created_at) }}</template></el-table-column><el-table-column label="操作" width="210" fixed="right"><template #default="s"><el-button text type="primary" @click="previewMaterial(s.row)">预览</el-button><el-button text @click="renameMaterial(s.row)">重命名</el-button><el-button text type="danger" @click="deleteMaterial(s.row)">删除</el-button></template></el-table-column></el-table>
          </section>
        </template>

        <template v-else-if="page === 'accounts'">
          <section class="panel"><div class="section-head"><div><span class="eyebrow">CHANNEL ACCOUNTS</span><h3>平台账号</h3><p>员工只能使用管理员分配给自己的账号。</p></div><el-button v-if="isAdmin" type="primary" @click="openAccountManager"><el-icon><Plus /></el-icon>添加账号</el-button></div>
            <el-table :data="accounts"><el-table-column label="平台" width="150"><template #default="s"><span class="platform-dot" :class="s.row.platform"></span>{{ platformName(s.row.platform) }}</template></el-table-column><el-table-column prop="display_name" label="账号备注名" /><el-table-column label="登录状态" width="130"><template #default="s"><el-tag :type="s.row.status === 'ready' ? 'success' : 'warning'">{{ statusName(s.row.status) }}</el-tag></template></el-table-column><el-table-column v-if="isAdmin" label="操作" width="300"><template #default="s"><el-button size="small" @click="startAccountLogin(s.row)">扫码登录</el-button><el-button size="small" @click="openAccess(s.row)">分配员工</el-button><el-button size="small" type="danger" plain @click="deleteAccount(s.row)">删除</el-button></template></el-table-column></el-table>
          </section>
        </template>

        <template v-else-if="page === 'users'">
          <section class="panel"><div class="section-head"><div><span class="eyebrow">TEAM ACCESS</span><h3>员工管理</h3><p>账号由管理员创建，系统不提供公开注册。</p></div><el-button type="primary" @click="userDialog=true"><el-icon><Plus /></el-icon>添加员工</el-button></div>
            <el-table :data="users"><el-table-column prop="display_name" label="姓名" /><el-table-column prop="username" label="用户名" /><el-table-column label="角色"><template #default="s"><el-tag>{{ s.row.role === 'admin' ? '管理员' : '操作员' }}</el-tag></template></el-table-column><el-table-column label="状态"><template #default="s"><el-switch v-model="s.row.active" :active-value="1" :inactive-value="0" @change="updateUser(s.row)" /></template></el-table-column><el-table-column label="创建时间"><template #default="s">{{ formatTime(s.row.created_at) }}</template></el-table-column><el-table-column label="操作" width="210"><template #default="s"><el-button text type="primary" @click="openRoleEditor(s.row)">修改角色</el-button><el-button text type="primary" @click="resetUserPassword(s.row)">重置密码</el-button></template></el-table-column></el-table>
          </section>
        </template>

        <template v-else-if="page === 'audit'">
          <section class="panel"><div class="section-head"><div><span class="eyebrow">SECURITY AUDIT</span><h3>操作日志</h3></div></div><el-table :data="audits"><el-table-column prop="display_name" label="操作人" width="140" /><el-table-column prop="action" label="动作" width="180" /><el-table-column prop="detail" label="详情" /><el-table-column prop="ip" label="IP" width="150" /><el-table-column label="时间" width="190"><template #default="s">{{ formatTime(s.row.created_at) }}</template></el-table-column></el-table></section>
        </template>
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="accountDialog" title="添加并登录平台账号" width="500px" :close-on-click-modal="false"><el-alert title="操作步骤：选择平台 → 填写便于识别的备注名 → 创建后使用平台 App 扫码登录" type="info" :closable="false" show-icon /><el-form label-position="top" class="account-form"><el-form-item label="第 1 步：选择平台"><el-select v-model="accountForm.platform"><el-option v-for="p in platforms" :key="p.value" :label="p.label" :value="p.value" /></el-select></el-form-item><el-form-item label="第 2 步：填写账号备注名"><el-input v-model="accountForm.display_name" placeholder="例如：运营抖音主账号" /><small class="field-tip">这里只是系统内显示的名称，不需要填写平台用户名或密码。</small></el-form-item></el-form><template #footer><el-button @click="accountDialog=false">取消</el-button><el-button type="primary" :loading="accountCreating" @click="createAccount">创建并扫码登录</el-button></template></el-dialog>
  <el-dialog v-model="userDialog" title="添加员工" width="460px"><el-form label-position="top"><el-form-item label="姓名"><el-input v-model="userForm.display_name" /></el-form-item><el-form-item label="用户名"><el-input v-model="userForm.username" /></el-form-item><el-form-item label="初始密码"><el-input v-model="userForm.password" type="password" show-password placeholder="至少10位" /></el-form-item><el-form-item label="角色"><el-radio-group v-model="userForm.role"><el-radio value="operator">操作员</el-radio><el-radio value="admin">管理员</el-radio></el-radio-group></el-form-item></el-form><template #footer><el-button @click="userDialog=false">取消</el-button><el-button type="primary" @click="createUser">创建</el-button></template></el-dialog>
  <el-dialog v-model="roleDialog" title="修改员工角色" width="420px"><p>正在修改：{{ roleEdit.display_name }}</p><el-radio-group v-model="roleEdit.role"><el-radio value="operator">操作员：只能使用被分配的平台账号</el-radio><el-radio value="admin">管理员：可管理员工、账号和发布任务</el-radio></el-radio-group><template #footer><el-button @click="roleDialog=false">取消</el-button><el-button type="primary" @click="saveUserRole">保存角色</el-button></template></el-dialog>
  <el-dialog v-model="accessDialog" title="分配账号使用权限" width="500px"><el-checkbox-group v-model="accessUserIds" class="access-list"><el-checkbox v-for="u in operatorUsers" :key="u.id" :value="u.id" border>{{ u.display_name }}（{{ u.username }}）</el-checkbox></el-checkbox-group><template #footer><el-button @click="accessDialog=false">取消</el-button><el-button type="primary" @click="saveAccess">保存权限</el-button></template></el-dialog>
  <el-dialog v-model="qrDialog" title="第 3 步：扫码登录平台账号" width="430px" :close-on-click-modal="false" @closed="stopQrPolling"><div class="qr-box"><el-skeleton v-if="!qrReady && !qrFailed" animated><template #template><el-skeleton-item variant="image" style="width:260px;height:260px" /></template></el-skeleton><img v-else-if="qrReady" :src="qrUrl" alt="登录二维码" @error="handleQrImageError" /><el-result v-else icon="error" title="登录未成功" :sub-title="qrError" /><h3 v-if="!qrFailed">{{ qrStatusText }}</h3><p v-if="!qrFailed">请使用对应平台 App 扫码并确认授权。若平台提示二维码失效，请点击“刷新二维码”。</p></div><template #footer><el-button @click="qrDialog=false">关闭</el-button><el-button type="primary" :loading="qrRefreshing" @click="refreshAccountLogin">刷新二维码</el-button></template></el-dialog>
  <el-dialog v-model="previewDialog" title="视频预览" width="720px"><video v-if="previewUrl" :src="previewUrl" controls autoplay class="video-preview" /></el-dialog>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const user = ref(null), csrf = ref(''), page = ref('dashboard'), loading = ref(false), uploading = ref(false), analysisLoading = ref(false)
const stats = reactive({}), accounts = ref([]), materials = ref([]), jobs = ref([]), users = ref([]), audits = ref([])
const loginForm = reactive({ username: 'admin', password: '' })
const publish = reactive({ material_id: null, platforms: [], account_ids: [], title: '', description: '', tags: '', schedule_at: '' })
const accountDialog = ref(false), accountCreating = ref(false), accountForm = reactive({ platform: 'douyin', display_name: '' })
const accountDialogSource = ref('accounts')
const userDialog = ref(false), userForm = reactive({ display_name: '', username: '', password: '', role: 'operator' })
const roleDialog = ref(false), roleEdit = reactive({ id: null, display_name: '', role: 'operator' })
const accessDialog = ref(false), accessAccount = ref(null), accessUserIds = ref([])
const qrDialog = ref(false), qrReady = ref(false), qrFailed = ref(false), qrError = ref(''), qrUrl = ref(''), qrStatusText = ref('正在生成二维码…'), qrAccount = ref(null), qrRefreshing = ref(false)
const previewDialog = ref(false), previewUrl = ref(''); let qrTimer, jobTimer
const platforms = [{value:'douyin',label:'抖音'},{value:'xiaohongshu',label:'小红书'},{value:'kuaishou',label:'快手'},{value:'bilibili',label:'B站'},{value:'tencent',label:'视频号'},{value:'youtube',label:'YouTube'}]
const isAdmin = computed(() => user.value?.role === 'admin')
const availablePlatforms = computed(() => platforms.filter(p => isAdmin.value || accounts.value.some(a => a.platform === p.value)))
const filteredPublishAccounts = computed(() => accounts.value.filter(a => publish.platforms.includes(a.platform)))
const operatorUsers = computed(() => users.value.filter(x => x.role === 'operator' && x.active))
const pageTitle = computed(() => ({dashboard:'工作台',publish:'新建发布',jobs:'发布记录',materials:'素材库',accounts:'平台账号',users:'员工管理',audit:'操作日志'}[page.value]))

const appBase = window.location.pathname.startsWith('/publisher') ? '/publisher' : ''
async function api(path, options={}) {
  const headers = {...(options.headers || {})}; if (csrf.value) headers['X-CSRF-Token'] = csrf.value
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch(appBase + '/api' + path, {...options, headers, credentials:'same-origin'})
  const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.message || '请求失败')
  return data
}
async function doLogin(){ loading.value=true; try{const x=await api('/auth/login',{method:'POST',body:JSON.stringify(loginForm)});user.value=x.user;csrf.value=x.csrf;await refresh()}catch(e){ElMessage.error(e.message)}finally{loading.value=false}}
async function logout(){try{await api('/auth/logout',{method:'POST'})}finally{user.value=null;csrf.value=''}}
async function restore(){try{const x=await api('/auth/me');user.value=x.user;csrf.value=x.csrf;await refresh()}catch{}}
async function refresh(){if(!user.value)return;try{const common=await Promise.all([api('/dashboard'),api('/accounts'),api('/materials'),api('/jobs')]);Object.assign(stats,common[0]);accounts.value=common[1];materials.value=common[2];jobs.value=common[3];if(isAdmin.value){[users.value,audits.value]=await Promise.all([api('/users'),api('/audit')])}}catch(e){ElMessage.error(e.message)}}
async function refreshJobProgress(){if(!user.value||!['dashboard','jobs'].includes(page.value)||!jobs.value.some(j=>['queued','running'].includes(j.status)))return;try{const [nextStats,nextJobs]=await Promise.all([api('/dashboard'),api('/jobs')]);Object.assign(stats,nextStats);jobs.value=nextJobs}catch{}}
function selectPage(x){page.value=x;if(x==='jobs')refresh()}
async function uploadMaterial(o){const f=new FormData();f.append('file',o.file);loading.value=true;try{await api('/materials',{method:'POST',body:f});ElMessage.success('素材上传成功');await refresh()}catch(e){ElMessage.error(e.message)}finally{loading.value=false}}
async function uploadAndSelectMaterial(o){const f=new FormData();f.append('file',o.file);uploading.value=true;try{const created=await api('/materials',{method:'POST',body:f});await refresh();publish.material_id=created.id;ElMessage.success('素材已上传，尚未发布；请继续选择平台账号并提交任务')}catch(e){ElMessage.error(e.message)}finally{uploading.value=false}}
async function analyzeMaterial(force=false){if(!publish.material_id||analysisLoading.value)return;const selectedId=publish.material_id;const cached=materials.value.find(m=>m.id===selectedId);if(!force&&cached?.analysis_title){publish.title=cached.analysis_title;publish.description=cached.analysis_description;publish.tags=cached.analysis_tags;ElMessage.success('已自动填写标题、简介和标签');return}analysisLoading.value=true;try{const x=await api(`/materials/${selectedId}/analyze`,{method:'POST',body:JSON.stringify({force})});if(publish.material_id===selectedId){publish.title=x.title;publish.description=x.description;publish.tags=x.tags}await refresh();ElMessage.success('已自动填写标题、简介和标签，请确认后发布')}catch(e){ElMessage.error(e.message)}finally{analysisLoading.value=false}}
async function createJob(){if(!publish.material_id)return ElMessage.warning('请选择视频素材');if(!publish.platforms.length)return ElMessage.warning('请选择至少一个发布平台');if(!publish.account_ids.length)return ElMessage.warning('请选择至少一个平台账号');const uncovered=publish.platforms.filter(p=>!publish.account_ids.some(id=>accounts.value.find(a=>a.id===id)?.platform===p));if(uncovered.length)return ElMessage.warning(`请为${uncovered.map(platformName).join('、')}选择发布账号`);loading.value=true;try{await api('/jobs',{method:'POST',body:JSON.stringify(publish)});ElMessage.success('发布任务已创建，正在提交至平台');Object.assign(publish,{material_id:null,platforms:[],account_ids:[],title:'',description:'',tags:'',schedule_at:''});page.value='jobs';await refresh()}catch(e){ElMessage.error(e.message)}finally{loading.value=false}}
function openAccountFromPublish(){accountDialogSource.value='publish';accountForm.platform=publish.platforms[0]||'douyin';accountDialog.value=true}
function openAccountManager(){accountDialogSource.value='accounts';accountDialog.value=true}
async function createAccount(){if(!accountForm.display_name.trim())return ElMessage.warning('请填写账号备注名');accountCreating.value=true;try{const created=await api('/accounts',{method:'POST',body:JSON.stringify(accountForm)});const selectedPlatform=accountForm.platform;accountDialog.value=false;Object.assign(accountForm,{platform:'douyin',display_name:''});await refresh();if(accountDialogSource.value==='publish'){if(!publish.platforms.includes(selectedPlatform))publish.platforms.push(selectedPlatform);if(!publish.account_ids.includes(created.id))publish.account_ids.push(created.id)}const row=accounts.value.find(a=>a.id===created.id);ElMessage.success('账号已创建，请完成扫码登录');if(row)await startAccountLogin(row)}catch(e){ElMessage.error(e.message)}finally{accountCreating.value=false}}
async function createUser(){try{await api('/users',{method:'POST',body:JSON.stringify(userForm)});userDialog.value=false;Object.assign(userForm,{display_name:'',username:'',password:'',role:'operator'});ElMessage.success('员工账号已创建');await refresh()}catch(e){ElMessage.error(e.message)}}
async function updateUser(row){try{await api('/users/'+row.id,{method:'PATCH',body:JSON.stringify({active:!!row.active})});ElMessage.success('状态已更新')}catch(e){ElMessage.error(e.message)}}
function openRoleEditor(row){Object.assign(roleEdit,{id:row.id,display_name:row.display_name,role:row.role});roleDialog.value=true}
async function saveUserRole(){try{await api('/users/'+roleEdit.id,{method:'PATCH',body:JSON.stringify({role:roleEdit.role})});roleDialog.value=false;ElMessage.success('员工角色已更新');await refresh()}catch(e){ElMessage.error(e.message)}}
async function resetUserPassword(row){try{const {value}=await ElMessageBox.prompt(`为 ${row.display_name} 设置新密码`,'重置员工密码',{inputType:'password',inputPlaceholder:'至少10位',inputValidator:v=>v.length>=10||'密码至少10位'});await api('/users/'+row.id,{method:'PATCH',body:JSON.stringify({password:value})});ElMessage.success('密码已重置')}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(e.message||'重置失败')}}
async function openAccess(row){accessAccount.value=row;try{const x=await api(`/accounts/${row.id}/access`);accessUserIds.value=x.user_ids;accessDialog.value=true}catch(e){ElMessage.error(e.message)}}
async function saveAccess(){try{await api(`/accounts/${accessAccount.value.id}/access`,{method:'PUT',body:JSON.stringify({user_ids:accessUserIds.value})});accessDialog.value=false;ElMessage.success('权限已保存')}catch(e){ElMessage.error(e.message)}}
async function deleteAccount(row){try{await ElMessageBox.confirm(`确定删除“${row.display_name}”吗？已产生发布记录的账号会被系统保护。`,'删除平台账号',{type:'warning',confirmButtonText:'确认删除',cancelButtonText:'取消'});await api(`/accounts/${row.id}`,{method:'DELETE'});ElMessage.success('平台账号已删除');await refresh()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(e.message)}}
function stopQrPolling(){clearInterval(qrTimer);qrTimer=undefined}
function handleQrImageError(){qrReady.value=false;qrStatusText.value='二维码图片加载失败，请点击刷新二维码'}
async function startAccountLogin(row){qrAccount.value=row;qrRefreshing.value=true;try{qrDialog.value=true;qrReady.value=false;qrFailed.value=false;qrError.value='';qrUrl.value='';qrStatusText.value='正在生成全新二维码…';stopQrPolling();await api(`/accounts/${row.id}/login`,{method:'POST'});qrTimer=setInterval(()=>pollLogin(row),2000);await pollLogin(row)}catch(e){qrFailed.value=true;qrError.value=e.message;ElMessage.error(e.message)}finally{qrRefreshing.value=false}}
async function refreshAccountLogin(){if(qrAccount.value)await startAccountLogin(qrAccount.value)}
async function pollLogin(row){try{const x=await api(`/accounts/${row.id}/login-status`);if(x.has_qr){qrReady.value=true;qrUrl.value=`${appBase}/api/accounts/${row.id}/qrcode?t=${Date.now()}`;qrStatusText.value='等待扫码确认'}if(x.status==='ready'){qrStatusText.value='登录成功';clearInterval(qrTimer);ElMessage.success('平台账号登录成功');setTimeout(()=>{qrDialog.value=false;refresh()},1000)}if(x.status==='failed'){qrFailed.value=true;qrError.value=x.message||'二维码登录失败，请关闭后重试';clearInterval(qrTimer)}}catch(e){qrFailed.value=true;qrError.value=e.message;clearInterval(qrTimer)}}
function previewMaterial(row){previewUrl.value=`${appBase}/api/materials/${row.id}/stream`;previewDialog.value=true}
async function renameMaterial(row){try{const {value}=await ElMessageBox.prompt('输入新的素材名称','重命名素材',{inputValue:row.original_name,inputValidator:v=>!!v.trim()||'名称不能为空'});await api(`/materials/${row.id}`,{method:'PATCH',body:JSON.stringify({name:value})});ElMessage.success('素材已重命名');await refresh()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(e.message)}}
async function deleteMaterial(row){try{await ElMessageBox.confirm(`确定删除“${row.original_name}”吗？删除后文件无法恢复。`,'删除素材',{type:'warning',confirmButtonText:'确认删除',cancelButtonText:'取消'});await api(`/materials/${row.id}`,{method:'DELETE'});if(publish.material_id===row.id)publish.material_id=null;ElMessage.success('素材和视频文件已删除');await refresh()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(e.message)}}
async function retryJob(job){try{await ElMessageBox.confirm(`重新执行任务 #${job.id} 的失败平台吗？已成功的平台不会重复发布。`,'重试发布',{type:'warning',confirmButtonText:'确认重试',cancelButtonText:'取消'});await api(`/jobs/${job.id}/retry`,{method:'POST'});ElMessage.success('失败任务已重新进入队列');await refresh()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(e.message)}}
function platformName(x){return platforms.find(p=>p.value===x)?.label||x}
function statusName(x){return {ready:'已登录',waiting_scan:'等待扫码',not_logged_in:'未登录',failed:'登录失败'}[x]||x}
function jobStatusName(x){return {queued:'排队中',running:'发布中',success:'发布成功',failed:'发布失败',partial_failed:'部分失败'}[x]||x}
function materialPublishName(x){return {not_published:'尚未创建发布任务',queued:'等待提交平台',running:'正在提交平台',success:'已提交平台',failed:'提交失败',partial_failed:'部分提交失败'}[x]||x}
function materialPublishType(x){return {not_published:'info',queued:'warning',running:'warning',success:'success',failed:'danger',partial_failed:'danger'}[x]||'info'}
function formatSize(n){return n>1073741824?(n/1073741824).toFixed(2)+' GB':(n/1048576).toFixed(1)+' MB'}
function formatTime(x){return x?new Date(x).toLocaleString('zh-CN'):'—'}

const JobTable = defineComponent({props:{jobs:Array},emits:['retry'],setup(props,{emit}){return()=>h('div',{class:'job-cards'},props.jobs?.length?props.jobs.map(j=>h('article',{class:'job-detail-card'},[
  h('header',{class:'job-detail-head'},[h('div',[h('b',j.title),h('span',`任务 #${j.id} · ${j.original_name}`)]),h('span',{class:'job-status '+j.status},jobStatusName(j.status))]),
  j.description?h('p',{class:'job-description'},j.description):null,
  h('div',{class:'job-meta'},[h('span','创建人：'+j.creator),h('span','创建：'+formatTime(j.created_at)),h('span','开始：'+formatTime(j.started_at)),h('span','完成：'+formatTime(j.finished_at)),j.schedule_at?h('span','计划：'+formatTime(j.schedule_at)):null,j.tags?h('span','标签：'+j.tags):null]),
  h('div',{class:'target-detail-list'},j.targets.map(t=>h('div',{class:'target-detail'},[
    h('div',{class:'target-detail-main'},[h('b',platformName(t.platform)+' · '+t.account_display),h('span',{class:'target '+t.status},jobStatusName(t.status))]),
    h('small',`开始：${formatTime(t.started_at)}　完成：${formatTime(t.finished_at)}`),
    t.output?h('details',[h('summary',t.status==='failed'?'查看失败原因':'查看执行详情'),h('pre',t.output)]):null
  ]))),['failed','partial_failed'].includes(j.status)?h('button',{class:'retry-button',onClick:()=>emit('retry',j)},'重试失败平台'):null
])):h('div',{class:'empty-state'},'暂无发布记录'))}})
watch(()=>publish.platforms.slice(), selected=>{publish.account_ids=publish.account_ids.filter(id=>selected.includes(accounts.value.find(a=>a.id===id)?.platform))})
watch(()=>publish.material_id, id=>{if(id)analyzeMaterial(false)})
onMounted(()=>{restore();jobTimer=setInterval(refreshJobProgress,3000)});onUnmounted(()=>{clearInterval(qrTimer);clearInterval(jobTimer)})
</script>

<style>
:root{--ink:#17221c;--muted:#708078;--paper:#f4f7f3;--line:#dfe7e1;--green:#216b43;--lime:#b9df5a;--nav:#13251c}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,"PingFang SC","Microsoft YaHei",sans-serif}.login-page{min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 75% 15%,#d9efad 0,transparent 26%),linear-gradient(135deg,#10251a,#254e35)}.login-panel{width:420px;background:#fff;padding:46px;border-radius:24px;box-shadow:0 30px 80px #06170d80}.brand-mark{display:grid;place-items:center;width:58px;height:58px;border-radius:16px;background:var(--lime);color:#17351f;font-weight:900;letter-spacing:-1px}.brand-mark.small{width:42px;height:42px;border-radius:12px;font-size:13px;flex:none}.login-panel h1{font-size:30px;margin:24px 0 8px}.login-panel p{color:var(--muted);margin:0 0 32px}.login-button{width:100%}.shell{min-height:100vh}.sidebar{background:var(--nav);color:white;display:flex;flex-direction:column;position:fixed;inset:0 auto 0 0;z-index:5}.brand{height:86px;padding:0 22px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #ffffff12}.brand b,.brand small{display:block}.brand small{font-size:9px;letter-spacing:1.5px;color:#9db5a7;margin-top:3px}.sidebar .el-menu{border:0;background:transparent;padding:18px 12px;flex:1}.sidebar .el-menu-item{color:#adbbb3;border-radius:10px;margin:4px 0}.sidebar .el-menu-item:hover,.sidebar .el-menu-item.is-active{background:#284636;color:white}.sidebar-user{display:flex;align-items:center;gap:10px;padding:18px;border-top:1px solid #ffffff12}.sidebar-user div{min-width:0;flex:1}.sidebar-user b,.sidebar-user small{display:block}.sidebar-user small{font-size:11px;color:#9db5a7}.shell>.el-container{margin-left:232px}.topbar{height:86px;padding:18px 34px;display:flex;justify-content:space-between;align-items:center;background:#fff;border-bottom:1px solid var(--line)}.topbar h2{margin:2px 0;font-size:22px}.eyebrow{font-size:10px;letter-spacing:1.8px;color:var(--green);font-weight:800}.el-main{padding:30px 34px}.hero{min-height:210px;padding:38px 42px;border-radius:24px;background:linear-gradient(115deg,#173c28,#2e7049);color:white;display:flex;align-items:center;justify-content:space-between;overflow:hidden;position:relative}.hero:after{content:"";position:absolute;width:270px;height:270px;border:55px solid #b9df5a22;border-radius:50%;right:120px;top:-100px}.hero h1{font-size:36px;margin:14px 0 6px}.hero p{color:#c7d8cd}.pill{background:var(--lime);color:#16351f;padding:6px 12px;border-radius:99px;font-size:12px;font-weight:700}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin:20px 0}.stat{background:white;padding:24px;border:1px solid var(--line);border-radius:16px}.stat span,.stat small{display:block;color:var(--muted)}.stat strong{font-size:36px;display:block;margin:10px 0}.stat.accent{background:#eaf5d7}.panel{background:white;border:1px solid var(--line);border-radius:18px;padding:26px;margin-bottom:22px}.section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}.section-head h3{font-size:22px;margin:4px 0}.section-head p{color:var(--muted);margin:4px 0}.two-col{display:grid;grid-template-columns:1fr 1fr;gap:20px}.publish-form{max-width:900px}.publish-form .el-select,.publish-form .el-date-editor{width:100%}.account-picker{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;width:100%}.account-picker .el-checkbox{margin:0;height:auto;padding:13px}.form-actions{display:flex;justify-content:flex-end}.platform-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;background:#777}.platform-dot.douyin{background:#111}.platform-dot.xiaohongshu{background:#e23a3a}.platform-dot.kuaishou{background:#ff5b25}.platform-dot.bilibili{background:#24a9d8}.platform-dot.tencent{background:#16b867}.platform-dot.youtube{background:#f00}.job-row{display:grid;grid-template-columns:minmax(220px,1fr) 1.4fr 170px;gap:20px;align-items:center;padding:16px 4px;border-top:1px solid var(--line)}.job-row:first-child{border-top:0}.job-main b,.job-main span{display:block}.job-main span,time{font-size:12px;color:var(--muted);margin-top:5px}.target-tags{display:flex;gap:6px;flex-wrap:wrap}.target{font-size:11px;padding:5px 8px;border-radius:7px;background:#eef1ef}.target.success{background:#dff3e6;color:#166038}.target.failed,.target.partial_failed{background:#fde5e1;color:#9f2d1e}.target.running{background:#fff1cc;color:#8a5b00}.access-list{display:grid;gap:10px}.access-list .el-checkbox{margin:0}.qr-box{text-align:center;padding:10px}.qr-box img{width:280px;height:280px;object-fit:contain}.qr-box p{color:var(--muted)}.video-preview{width:100%;max-height:65vh;background:#000}.empty-state{text-align:center;color:var(--muted);padding:50px}@media(max-width:900px){.sidebar{width:72px!important}.brand>div,.sidebar-user>div,.sidebar-user .el-button{display:none}.brand{padding:0 15px}.shell>.el-container{margin-left:72px}.stats{grid-template-columns:repeat(2,1fr)}.two-col,.account-picker{grid-template-columns:1fr}.el-main{padding:18px}.job-row{grid-template-columns:1fr}.topbar{padding:16px 20px}}
.platform-picker{display:flex;flex-wrap:wrap;gap:10px}.platform-picker .el-checkbox{margin:0}.account-heading{width:100%;display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;color:var(--muted)}
.material-select{display:flex;width:100%;gap:10px}.material-select>.el-select{flex:1}.field-tip{display:block;color:var(--muted);line-height:1.6;margin-top:5px}.account-form{margin-top:20px}.account-form .el-select{width:100%}
.analyze-button{margin-top:10px}.job-detail-card{border:1px solid var(--line);border-radius:14px;padding:20px;margin-top:14px;background:#fbfcfb}.job-detail-card:first-child{margin-top:0}.job-detail-head{display:flex;justify-content:space-between;gap:20px}.job-detail-head b,.job-detail-head span{display:block}.job-detail-head>div>span{font-size:12px;color:var(--muted);margin-top:6px}.job-status{padding:6px 10px;border-radius:8px;height:fit-content;font-size:12px;background:#eef1ef}.job-status.success{background:#dff3e6;color:#166038}.job-status.failed,.job-status.partial_failed{background:#fde5e1;color:#9f2d1e}.job-status.running{background:#fff1cc;color:#8a5b00}.job-description{color:#47564e}.job-meta{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:12px;color:var(--muted);padding:12px 0;border-top:1px dashed var(--line)}.target-detail-list{display:grid;gap:8px}.target-detail{background:white;border:1px solid var(--line);border-radius:10px;padding:12px}.target-detail-main{display:flex;align-items:center;justify-content:space-between}.target-detail small{display:block;color:var(--muted);margin-top:6px}.target-detail details{margin-top:8px}.target-detail summary{cursor:pointer;color:var(--green);font-size:12px}.target-detail pre{white-space:pre-wrap;word-break:break-word;max-height:280px;overflow:auto;background:#14221b;color:#dbe8df;padding:12px;border-radius:8px;font-size:11px}
.analysis-status{margin-top:10px}
.retry-button{margin-top:12px;border:0;border-radius:8px;padding:8px 12px;background:#fff1cc;color:#7a5200;cursor:pointer;font-weight:600}.retry-button:hover{background:#ffe5a0}
</style>
