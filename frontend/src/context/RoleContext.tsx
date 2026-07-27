import { createContext, useContext, type ReactNode } from 'react'
import { useAuth } from './AuthContext'

export type Role='集团财务总监 / 最终审批人'|'财务审批主管'|'信用审核专员'|'业务申请人'
export const ROLES:Role[]=['集团财务总监 / 最终审批人','财务审批主管','信用审核专员','业务申请人']
export const ROLE_DESC:Record<Role,string>={
  '集团财务总监 / 最终审批人':'在主管复核后最终批核信审，并处理阻断级、重大商业例外和系统治理',
  '财务审批主管':'复核信用审核专员的信审建议，处理主管级合同例外，再上报重大事项',
  '信用审核专员':'评估信用条件、提交主管复核，完成合同初审、补件与常规放行',
  '业务申请人':'发起信审与合同申请，提供业务资料、选择生效信审版本并处理本人补件',
}
const map:Record<string,Role>={admin:'集团财务总监 / 最终审批人',director:'财务审批主管',reviewer:'信用审核专员',business:'业务申请人'}
const Ctx=createContext<{role:Role;setRole:(r:Role)=>void}>({role:'业务申请人',setRole:()=>{}})
export function RoleProvider({children}:{children:ReactNode}){const {user}=useAuth();return <Ctx.Provider value={{role:map[user?.role||'business'],setRole:()=>{}}}>{children}</Ctx.Provider>}
export const useRole=()=>useContext(Ctx)
