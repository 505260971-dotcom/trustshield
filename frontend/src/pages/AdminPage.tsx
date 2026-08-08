import { useEffect, useState } from 'react'
import { Alert, Button, Card, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { AuditOutlined, DeleteOutlined, EditOutlined, ExclamationCircleOutlined, PlusOutlined, TeamOutlined } from '@ant-design/icons'
import { api } from '../services/api'
import { fmtTime } from '../components/common'
import { useAuth } from '../context/AuthContext'

const { Text } = Typography
const labels:Record<string,string> = {admin:'系统管理员',final_approver:'集团财务总监（最终审批人）',director:'财务审批主管',reviewer:'信用审核专员',business:'业务申请人'}
const roleOptions=['business','reviewer','director','final_approver','admin'].map(value=>({value,label:labels[value]}))
type User = {id:string;username:string;display_name:string;role:string;active:number;created_at:number;updated_at:number}

export default function AdminPage(){
  const {user:currentUser}=useAuth()
  const [users,setUsers]=useState<User[]>([])
  const [audit,setAudit]=useState<any[]>([])
  const [userOpen,setUserOpen]=useState(false)
  const [editingUser,setEditingUser]=useState<User|null>(null)
  const [resetting,setResetting]=useState(false)
  const [userForm]=Form.useForm()

  const load=async()=>{
    try{
      const [u,a]=await Promise.all([api.adminUsers(),api.audit()])
      setUsers(u.items);setAudit(a.items)
    }catch(e:any){message.error(e.message||'加载管理数据失败')}
  }
  useEffect(()=>{load()},[])
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
  const confirmResetBusinessData=()=>{
    Modal.confirm({
      title:'重置全部业务演示数据？',
      icon:<ExclamationCircleOutlined />,
      content:'这会永久删除信审案件、财报与额度快照、合同案件、审查结果、风险动作、审批/补件/翻译/导出记录、流程任务、审计历史和上传材料。人员账户、LLM/重排/Embedding 配置、规则版本、信用模型及审批路径不会被删除。当前操作不可恢复。',
      okText:'确认清空',
      okButtonProps:{danger:true},
      cancelText:'取消',
      onOk:async()=>{
        setResetting(true)
        try{
          const result=await api.resetBusinessData()
          const errors=result?.file_cleanup_errors?.length||0
          if(errors)message.warning(`业务记录已重置，但有 ${errors} 个上传文件未能删除，请检查数据目录`)
          else message.success(`业务演示数据已重置，共清理 ${result?.deleted_total||0} 条记录`)
          await load()
        }catch(e:any){message.error(e.message||'业务数据重置失败')}finally{setResetting(false)}
      },
    })
  }

  const activeMembers=users.filter(member=>member.active).length
  return <div className="role-page governance-page">
    <section className="page-hero page-hero-light governance-hero">
      <div><span className="section-kicker">系统治理</span><Typography.Title level={2}>组织与权限</Typography.Title><Typography.Paragraph>统一维护成员账号、系统运行配置和操作审计。信用审核由信用审核专员确认生效；后续商业决策在合同审批阶段完成。合同风险条款由信用审核专员起草、财务审批主管复核发布，不在此处维护。</Typography.Paragraph></div>
      <div className="page-hero-actions"><Tag color="purple">仅系统管理员可维护</Tag><Tag color="green">审计全程留痕</Tag></div>
    </section>
    <section className="compact-metrics" aria-label="治理概览">
      <div className="compact-metric"><span className="compact-metric-icon"><TeamOutlined/></span><div><small>启用成员</small><strong>{activeMembers}</strong><em>共 {users.length} 个账户</em></div></div>
      <div className="compact-metric metric-attention"><span className="compact-metric-icon"><AuditOutlined/></span><div><small>信用确认</small><strong>1</strong><em>审核专员确认后直接生效</em></div></div>
      <div className="compact-metric metric-warning"><span className="compact-metric-icon"><AuditOutlined/></span><div><small>合同审批关口</small><strong>2</strong><em>主管和终审均可退回或驳回</em></div></div>
      <div className="compact-metric"><span className="compact-metric-icon"><AuditOutlined/></span><div><small>审计记录</small><strong>{audit.length}</strong><em>当前加载的操作日志</em></div></div>
    </section>
    {!users.some(member=>member.active&&member.role==='final_approver')&&<Alert showIcon type="warning" style={{marginBottom:16}} message="尚未配置最终审批人" description="需要集团财务总监终审的合同将无法上报。请先创建并启用至少一名“集团财务总监（最终审批人）”。信用审核仍由信用审核专员确认后直接生效。"/>}
    <Card className="governance-card" title="业务演示数据重置" extra={<Button danger loading={resetting} icon={<DeleteOutlined/>} onClick={confirmResetBusinessData}>重置全部业务记录</Button>}>
      <Alert showIcon type="warning" message="仅清理业务数据，不影响登录和模型配置" description="用于重新开始一轮演示。会清除所有信审、合同审查及其材料、评估、风险、审批、补件、流程任务、审计历史和上传文件；人员账户、LLM 配置、重排/向量配置、规则版本、信用模型和审批路径会保留。执行前请确认当前没有需要保留的记录。"/>
    </Card>
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

    <Card className="governance-card" title="信用审核确认机制">
      <Alert showIcon type="success" message="信用审核专员确认即生效" description="系统管理员不再配置重复的信用审核主管/终审路径。审核专员负责确认授信条件及每条联网公开信息是否纳入；已纳入的来源、理由和授信条件会冻结到合同审查报告，财务审批主管和集团财务总监在合同审批时可查看、退回或驳回合同。"/>
      <Text type="secondary" style={{display:'block',marginTop:12}}>历史审批路径版本仅用于已存在的历史记录追溯，不会影响新信用审核版本。</Text>
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

  </div>
}
