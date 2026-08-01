import { createContext, useContext, type ReactNode } from 'react'
import { useAuth } from './AuthContext'

export type Role='集团财务总监 / 最终审批人'|'财务审批主管'|'信用审核专员'|'业务申请人'
export const ROLES:Role[]=['集团财务总监 / 最终审批人','财务审批主管','信用审核专员','业务申请人']
export const ROLE_DESC:Record<Role,string>={
  '集团财务总监 / 最终审批人':'在主管复核后完成最终审批，并处理重大风险、商业例外和系统治理事项',
  '财务审批主管':'复核信用审核专员的审核建议，处理主管级合同例外，并上报重大事项',
  '信用审核专员':'评估客户信用条件，复核合同风险，处理补充材料并提交审批',
  '业务申请人':'发起信用审核和合同申请，提供业务材料，处理退回事项',
}
const map:Record<string,Role>={admin:'集团财务总监 / 最终审批人',director:'财务审批主管',reviewer:'信用审核专员',business:'业务申请人'}
const Ctx=createContext<{role:Role;setRole:(r:Role)=>void}>({role:'业务申请人',setRole:()=>{}})
export function RoleProvider({children}:{children:ReactNode}){const {user}=useAuth();return <Ctx.Provider value={{role:map[user?.role||'business'],setRole:()=>{}}}>{children}</Ctx.Provider>}
export const useRole=()=>useContext(Ctx)
