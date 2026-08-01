import { useEffect, useState } from 'react'
import { Alert, Button, Card, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { AuditOutlined, DeleteOutlined, EditOutlined, PlusOutlined, TeamOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { fmtTime } from '../components/common'
import { useAuth } from '../context/AuthContext'
import type { CreditRouteVersion, RuleItem, RuleVersion } from '../types'

const { Text } = Typography
const businessTypes = ['全部', '一般', '模塑一体', 'TKM', 'TKP', '采购订单']
const labels:Record<string,string> = {admin:'集团财务总监（最终审批人）',director:'财务审批主管',reviewer:'信用审核专员',business:'业务申请人'}
const versionStatusText:Record<string,string> = { draft:'草稿', published:'已发布', archived:'已归档' }
const roleOptions=['business','reviewer','director','admin'].map(value=>({value,label:labels[value]}))
type User = {id:string;username:string;display_name:string;role:string;active:number;created_at:number;updated_at:number}

export default function AdminPage(){
  const {user:currentUser}=useAuth()
  const [users,setUsers]=useState<User[]>([])
  const [audit,setAudit]=useState<any[]>([])
  const [versions,setVersions]=useState<RuleVersion[]>([])
  const [selectedVersion,setSelectedVersion]=useState('')
  const [rules,setRules]=useState<RuleItem[]>([])
  const [routeVersions,setRouteVersions]=useState<CreditRouteVersion[]>([])
  const [selectedRouteVersion,setSelectedRouteVersion]=useState('')
  const [route,setRoute]=useState<CreditRouteVersion|null>(null)
  const [userOpen,setUserOpen]=useState(false)
  const [editingUser,setEditingUser]=useState<User|null>(null)
  const [ruleOpen,setRuleOpen]=useState(false)
  const [editing,setEditing]=useState<RuleItem|null>(null)
  const [userForm]=Form.useForm()
  const [ruleForm]=Form.useForm()
  const [routeForm]=Form.useForm()

  const load=async()=>{
    try{
      const [u,a,v,r]=await Promise.all([api.adminUsers(),api.audit(),api.ruleVersions(),api.creditRouteVersions()])
      setUsers(u.items);setAudit(a.items);setVersions(v.items);setRouteVersions(r.items)
      const active=selectedVersion||v.items.find((x:RuleVersion)=>x.status==='published')?.version||''
      if(active)await loadRules(active)
      const activeRoute=selectedRouteVersion||r.items.find((x:CreditRouteVersion)=>x.status==='published')?.version||''
      if(activeRoute)await loadRoute(activeRoute)
    }catch(e:any){message.error(e.message||'加载管理数据失败')}
  }
  const loadRules=async(version:string)=>{try{const result=await api.ruleVersion(version);setSelectedVersion(version);setRules(result.rules)}catch(e:any){message.error(e.message||'加载规则版本失败')}}
  const loadRoute=async(version:string)=>{try{const result=await api.creditRouteVersion(version);setSelectedRouteVersion(version);setRoute(result);routeForm.setFieldsValue(result.config)}catch(e:any){message.error(e.message||'加载信用审核审批路径失败')}}
  useEffect(()=>{load()},[])
  const selected=versions.find(x=>x.version===selectedVersion)
  const editable=selected?.status==='draft'
  const closeUser=()=>{setUserOpen(false);setEditingUser(null);userForm.resetFields()}
  const openCreateUser=()=>{setEditingUser(null);userForm.resetFields();userForm.setFieldsValue({role:'reviewer',active:true});setUserOpen(true)}
  const openEditUser=(member:User)=>{setEditingUser(member);userForm.resetFields();userForm.setFieldsValue({username:member.username,display_name:member.display_name,role:member.role,active:!!member.active,password:''});setUserOpen(true)}
  const saveUser=async(values:any)=>{
    try{
      if(editingUser){
        const patch:any={display_name:values.display_name,role:values.role,active:values.active}
        if(values.password?.trim())patch.password=values.password
        await api.patchUser(editingUser.id,patch)
        message.success('成员信息已更新')
      }else{
        await api.createUser({username:values.username,display_name:values.display_name,role:values.role,password:values.password})
        message.success('成员已创建，可以使用新账号登录')
      }
      closeUser();load()
    }catch(e:any){message.error(e.message||'保存成员失败')}
  }
  const patchUser=async(id:string,values:any)=>{try{await api.patchUser(id,values);message.success('成员状态已更新');load()}catch(e:any){message.error(e.message||'更新失败')}}
  const removeUser=async(member:User)=>{try{await api.deleteUser(member.id);message.success('成员已永久删除，无法恢复');load()}catch(e:any){message.error(e.message||'删除失败')}}
  const createDraft=async()=>{try{const result=await api.createRuleDraft();message.success('已创建草稿 '+result.version);setVersions([]);await load();await loadRules(result.version)}catch(e:any){message.error(e.message||'创建草稿失败')}}
  const editRule=(rule:RuleItem)=>{setEditing(rule);ruleForm.setFieldsValue({...rule,applies_to:rule.applies_to||['全部']});setRuleOpen(true)}
  const saveRule=async()=>{try{const values=await ruleForm.validateFields();if(!editing)return;await api.updateRule(selectedVersion,editing.id,values);message.success('规则草稿已保存');setRuleOpen(false);await loadRules(selectedVersion)}catch(e:any){if(e?.errorFields)return;message.error(e.message||'规则保存失败')}}
  const publish=async()=>{try{await api.publishRuleVersion(selectedVersion);message.success('规则版本已发布，新发起的审查将使用此版本');await load()}catch(e:any){message.error(e.message||'发布失败')}}
  const createRouteDraft=async()=>{try{const result=await api.createCreditRouteDraft();message.success('已创建信用审核审批路径草稿 '+result.version);await load();await loadRoute(result.version)}catch(e:any){message.error(e.message||'创建审批路径草稿失败')}}
  const saveRoute=async()=>{try{if(!route)return;const config=await routeForm.validateFields();await api.updateCreditRoute(route.version,config);message.success('信用审核审批路径草稿已保存');await loadRoute(route.version)}catch(e:any){if(e?.errorFields)return;message.error(e.message||'保存审批路径草稿失败')}}
  const publishRoute=async()=>{try{if(!route)return;await api.publishCreditRouteVersion(route.version);message.success('信用审核审批路径已发布，新提交的信用审核将按此路径处理');await load()}catch(e:any){message.error(e.message||'发布审批路径失败')}}

  const activeMembers=users.filter(member=>member.active).length
  const draftCount=versions.filter(version=>version.status==='draft').length+(route?.status==='draft'?1:0)
  return <div className="role-page governance-page">
    <section className="page-hero page-hero-light governance-hero">
      <div><span className="section-kicker">权限与规则</span><Typography.Title level={2}>组织与规则</Typography.Title><Typography.Paragraph>统一维护成员权限、合同底线和信用审核审批路径。规则和审批路径均通过“草稿—发布”生效，已进入流程的案件会保留当时使用的版本。</Typography.Paragraph></div>
      <div className="page-hero-actions"><Tag color="purple">仅最终审批人可维护</Tag><Tag color="green">审计全程留痕</Tag></div>
    </section>
    <section className="compact-metrics" aria-label="治理概览">
      <div className="compact-metric"><span className="compact-metric-icon"><TeamOutlined/></span><div><small>启用成员</small><strong>{activeMembers}</strong><em>共 {users.length} 个账户</em></div></div>
      <div className="compact-metric metric-attention"><span className="compact-metric-icon"><AuditOutlined/></span><div><small>规则版本</small><strong>{versions.length}</strong><em>{selected?.status==='draft'?'当前正在编辑草稿':'当前查看已发布版本'}</em></div></div>
      <div className="compact-metric metric-warning"><span className="compact-metric-icon"><AuditOutlined/></span><div><small>待发布草稿</small><strong>{draftCount}</strong><em>发布前请完成复核</em></div></div>
      <div className="compact-metric"><span className="compact-metric-icon"><AuditOutlined/></span><div><small>审计记录</small><strong>{audit.length}</strong><em>当前加载的操作日志</em></div></div>
    </section>
    <div className="governance-stack">
    <Card className="member-admin-card" title={<Space><TeamOutlined/>团队成员与分级审批权限</Space>} extra={<Button type="primary" icon={<PlusOutlined/>} onClick={openCreateUser}>新增成员</Button>}>
      <Alert showIcon type="info" style={{marginBottom:16}} message="成员账户管理" description="管理员可新增、编辑、重置密码、停用或永久删除账户。永久删除不可恢复；系统会阻止删除当前登录账户或最后一名启用的最终审批人。"/>
      <Table rowKey="id" dataSource={users} pagination={{pageSize:8}} scroll={{x:900}} columns={[
        {title:'成员',key:'member',render:(_:unknown,row:User)=><Space direction="vertical" size={0}><Text strong>{row.display_name}</Text><Text type="secondary">{row.username}</Text></Space>},
        {title:'岗位',dataIndex:'role',render:(value:string)=><Tag color={value==='admin'?'red':value==='reviewer'?'cyan':value==='director'?'purple':'blue'}>{labels[value]||value}</Tag>},
        {title:'状态',dataIndex:'active',render:(value:number,row:User)=><Space><Switch checked={!!value} disabled={row.id===currentUser?.id} onChange={active=>patchUser(row.id,{active})}/><Text type={value?'success':'secondary'}>{value?'启用':'停用'}</Text></Space>},
        {title:'最近更新',dataIndex:'updated_at',render:fmtTime},
        {title:'操作',key:'actions',width:190,render:(_:unknown,row:User)=><Space size={4}><Button size="small" icon={<EditOutlined/>} onClick={()=>openEditUser(row)}>编辑</Button><Popconfirm title="永久删除该成员？" description="账号将无法登录，且不可恢复。" okText="永久删除" okButtonProps={{danger:true}} cancelText="取消" disabled={row.id===currentUser?.id} onConfirm={()=>removeUser(row)}><Button size="small" danger disabled={row.id===currentUser?.id} icon={<DeleteOutlined/>}>删除</Button></Popconfirm></Space>}
      ]}/>
    </Card>

    <Card className="governance-card" title="合同底线规则版本" extra={<Space><Button onClick={createDraft} icon={<PlusOutlined/>}>从已发布版本创建草稿</Button>{editable&&<Popconfirm title={'发布 '+selectedVersion+' 后将替换当前生效版本，确认吗？'} onConfirm={publish}><Button type="primary">发布草稿</Button></Popconfirm>}</Space>}>
      <Space style={{marginBottom:12}} wrap><Text type="secondary">当前查看：</Text><Select value={selectedVersion||undefined} style={{minWidth:220}} onChange={loadRules} options={versions.map(version=>({value:version.version,label:version.version+' · '+(versionStatusText[version.status]||version.status)}))}/>{selected&&<Tag color={selected.status==='published'?'green':selected.status==='draft'?'orange':'default'}>{versionStatusText[selected.status]||selected.status}</Tag>}</Space>
      <Table rowKey="id" dataSource={rules} size="small" pagination={{pageSize:8}} scroll={{x:900}} columns={[
        {title:'规则',dataIndex:'id',width:72,render:(value:string,rule:RuleItem)=><Tag color={rule.severity==='high'?'red':'orange'}>{value}</Tag>},
        {title:'规则底线',dataIndex:'baseline',width:260},{title:'适用业务',dataIndex:'applies_to',width:150,render:(value:string[])=>value?.join('、')},
        {title:'例外审批',dataIndex:'approval_role',width:120,render:(value:string)=>value?labels[value]||value:'—'},
        {title:'建议改写',dataIndex:'template',ellipsis:true},{title:'操作',width:80,render:(_:unknown,rule:RuleItem)=><Button disabled={!editable} size="small" icon={<EditOutlined/>} onClick={()=>editRule(rule)}>编辑</Button>}
      ]}/>
    </Card>

    <Card className="governance-card" title="信用审核审批路径" extra={<Space><Button onClick={createRouteDraft} icon={<PlusOutlined/>}>从已发布版本创建草稿</Button>{route?.status==='draft'&&<><Button onClick={saveRoute}>保存草稿</Button><Popconfirm title={'发布 '+route.version+' 后将替换当前生效审批路径，确认吗？'} onConfirm={publishRoute}><Button type="primary">发布草稿</Button></Popconfirm></>}</Space>}>
      <Alert showIcon type="info" style={{marginBottom:16}} message="统一管理审批路径" description="每份信用审核先由财务审批主管复核；只有达到额度、账期、预付款、承兑汇票、VMI/JIT 或人工修订等条件时，才提交集团财务总监最终审批。已提交的案件会保留当时使用的审批路径，不受后续发布影响。"/>
      <Space style={{marginBottom:12}} wrap><Text type="secondary">当前查看：</Text><Select value={selectedRouteVersion||undefined} style={{minWidth:240}} onChange={loadRoute} options={routeVersions.map(version=>({value:version.version,label:version.version+' · '+(versionStatusText[version.status]||version.status)}))}/>{route&&<Tag color={route.status==='published'?'green':route.status==='draft'?'orange':'default'}>{versionStatusText[route.status]||route.status}</Tag>}</Space>
      {route&&<Form form={routeForm} layout="vertical" disabled={route.status!=='draft'}><Space wrap align="start"><Form.Item name="final_threshold_amount" label="提交最终审批：额度不低于" rules={[{required:true}]}><InputNumber min={0} precision={2} addonAfter="CNY"/></Form.Item><Form.Item name="final_threshold_payment_days" label="提交最终审批：账期不低于" rules={[{required:true}]}><InputNumber min={0} addonAfter="天"/></Form.Item><Form.Item name="final_threshold_prepayment_ratio" label="提交最终审批：最低预付款比例不高于" rules={[{required:true}]}><InputNumber min={0} max={100} addonAfter="%"/></Form.Item></Space><Space wrap><Form.Item name="final_on_manual_override" label="人工修订或兜底审批" valuePropName="checked"><Switch checkedChildren="提交终审" unCheckedChildren="主管结束"/></Form.Item><Form.Item name="final_on_acceptance_bill" label="包含承兑汇票" valuePropName="checked"><Switch checkedChildren="提交终审" unCheckedChildren="主管结束"/></Form.Item><Form.Item name="final_on_vmi_jit" label="允许 VMI/JIT" valuePropName="checked"><Switch checkedChildren="提交终审" unCheckedChildren="主管结束"/></Form.Item></Space><Form.Item name="director_required" hidden valuePropName="checked"><Switch/></Form.Item></Form>}
    </Card>

    <Card className="governance-card" title={<Space><AuditOutlined/>合同评审审计日志</Space>}>
      <Table size="small" rowKey="event_id" dataSource={audit} pagination={{pageSize:8}} scroll={{x:900}} columns={[
        {title:'时间',dataIndex:'created_at',render:fmtTime},{title:'动作',dataIndex:'action'},
        {title:'资源',render:(_:unknown,row:any)=>(row.resource_type||'—')+' / '+(row.resource_id||'—')},
        {title:'操作者',dataIndex:'actor_role',render:(value:string)=>labels[value]||value},{title:'详细信息',dataIndex:'metadata',render:(value:any)=><Text type="secondary">{JSON.stringify(value)}</Text>}
      ]}/>
    </Card>

    </div>
    <Drawer title={editingUser?'编辑成员':'新增合同审核成员'} open={userOpen} onClose={closeUser} width={460} extra={<Button type="primary" onClick={()=>userForm.submit()}>{editingUser?'保存修改':'创建成员'}</Button>}>
      <Alert showIcon type="info" style={{marginBottom:16}} message={editingUser?'可修改姓名、岗位、启用状态和登录密码。':'创建后，成员可以按所选岗位看到对应的工作台。'}/>
      <Form form={userForm} layout="vertical" onFinish={saveUser} initialValues={{role:'reviewer',active:true}}>
        <Form.Item name="display_name" label="姓名" rules={[{required:true,message:'请填写成员姓名'},{max:80}]}><Input autoComplete="off" placeholder="例如：李审" /></Form.Item>
        <Form.Item name="username" label="登录用户名" rules={[{required:true,message:'请填写登录用户名'},{min:3,message:'用户名至少 3 个字符'},{max:80}]} extra={editingUser?'用户名创建后不可修改。':'建议使用英文、数字或易识别的拼音。'}><Input disabled={!!editingUser} autoComplete="off" placeholder="例如：credit_reviewer" /></Form.Item>
        <Form.Item name="role" label="岗位角色" rules={[{required:true,message:'请选择岗位角色'}]}><Select options={roleOptions}/></Form.Item>
        {editingUser&&<Form.Item name="active" label="账户状态" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" disabled={editingUser.id===currentUser?.id}/></Form.Item>}
        <Form.Item name="password" label={editingUser?'重置登录密码':'初始登录密码'} rules={[...(editingUser?[]:[{required:true,message:'请设置初始密码'}]),{min:10,message:'密码至少需要 10 个字符'},{max:256}]} extra={editingUser?'留空表示不修改密码；填写后将立即替换旧密码。':'密码至少 10 个字符，建议使用大小写字母、数字和符号。'}><Input.Password autoComplete="new-password" placeholder={editingUser?'留空不修改':'至少 10 个字符'} /></Form.Item>
      </Form>
    </Drawer>

    <Modal title={'编辑 '+(editing?.id||'')+' 草稿规则'} open={ruleOpen} onCancel={()=>setRuleOpen(false)} onOk={saveRule} okText="保存草稿">
      <Form form={ruleForm} layout="vertical"><Form.Item name="baseline" label="底线规则" rules={[{required:true}]}><Input.TextArea rows={2}/></Form.Item><Form.Item name="check" label="规则判定说明" rules={[{required:true}]}><Input.TextArea rows={2}/></Form.Item><Form.Item name="severity" label="风险等级" rules={[{required:true}]}><Select options={['high','mid','low'].map(value=>({value,label:value==='high'?'高风险':value==='mid'?'中风险':'低风险'}))}/></Form.Item><Form.Item name="applies_to" label="适用业务类型" rules={[{required:true}]}><Select mode="multiple" options={businessTypes.map(value=>({value,label:value}))}/></Form.Item><Form.Item name="approval_role" label="例外审批层级"><Select allowClear options={[{value:'director',label:'财务审批主管'},{value:'admin',label:'集团财务总监（最终审批人）'}]}/></Form.Item><Form.Item name="template" label="建议改写模板" rules={[{required:true}]}><Input.TextArea rows={3}/></Form.Item></Form>
    </Modal>
  </div>
}
