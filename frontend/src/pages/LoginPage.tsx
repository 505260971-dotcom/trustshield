import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Space, Typography, message } from 'antd'
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from '../context/AuthContext'
const {Title,Text}=Typography
export default function LoginPage(){
 const {login}=useAuth(); const [busy,setBusy]=useState(false)
 const submit=async(v:{username:string,password:string})=>{setBusy(true);try{await login(v.username,v.password);message.success('登录成功')}catch{message.error('登录失败，请检查账号、密码或服务端环境变量')}finally{setBusy(false)}}
 return <div className="login-shell"><Card className="login-card" bordered={false}>
  <Space direction="vertical" size={18} style={{width:'100%',textAlign:'center'}}><SafetyCertificateOutlined style={{fontSize:44,color:'#1677ff'}}/><div><Title level={2} style={{margin:0}}>TrustShield</Title><Text type="secondary">合同评审协作中心</Text></div>
  <Alert type="info" showIcon message="请使用管理员创建的账号登录，系统会根据你的岗位分配权限。"/>
  <Form layout="vertical" onFinish={submit}><Form.Item name="username" label="用户名" rules={[{required:true}]}><Input prefix={<UserOutlined/>} autoComplete="username"/></Form.Item><Form.Item name="password" label="密码" rules={[{required:true}]}><Input.Password prefix={<LockOutlined/>} autoComplete="current-password"/></Form.Item><Button type="primary" htmlType="submit" block loading={busy}>登录</Button></Form>
  </Space></Card></div>
}
