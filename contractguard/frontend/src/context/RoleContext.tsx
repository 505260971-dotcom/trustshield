import { createContext, useContext, type ReactNode } from 'react'
import { useAuth } from './AuthContext'

export type Role='管理员'|'信审人员'|'法务'|'总监'|'CEO'|'业务人员'
export const ROLES:Role[]=['管理员','信审人员','法务','总监','CEO','业务人员']
export const ROLE_DESC:Record<Role,string>={'管理员':'管理团队成员、规则、信审与全量审计','信审人员':'创建、更新并审批客户信审条件','法务':'领取案件、处置合同法律风险并交付审查意见','总监':'处理高风险条款与关键业务例外','CEO':'处理阻断级风险与特别审批','业务人员':'选择已生效信审版本后提交合同、跟进本人案件'}
const map:Record<string,Role>={admin:'管理员',credit:'信审人员',legal:'法务',director:'总监',ceo:'CEO',business:'业务人员'}
const Ctx=createContext<{role:Role;setRole:(r:Role)=>void}>({role:'业务人员',setRole:()=>{}})
export function RoleProvider({children}:{children:ReactNode}){const {user}=useAuth();return <Ctx.Provider value={{role:map[user?.role||'business'],setRole:()=>{}}}>{children}</Ctx.Provider>}
export const useRole=()=>useContext(Ctx)
