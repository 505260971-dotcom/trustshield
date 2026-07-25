import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../services/api'

export type User = { id:string; username:string; display_name:string; role:string; active:number }
type Auth = { user:User|null; token:string; loading:boolean; login:(username:string,password:string)=>Promise<void>; logout:()=>void }
const Ctx=createContext<Auth>({user:null,token:'',loading:true,login:async()=>{},logout:()=>{}})

export function AuthProvider({children}:{children:ReactNode}) {
  const [user,setUser]=useState<User|null>(null); const [token,setToken]=useState(localStorage.getItem('cg_token')||''); const [loading,setLoading]=useState(true)
  useEffect(()=>{ api.setToken(token); if(!token){setLoading(false);return}; api.me().then(r=>setUser(r.user)).catch(()=>{localStorage.removeItem('cg_token');setToken('')}).finally(()=>setLoading(false)) },[token])
  const login=async(username:string,password:string)=>{ const r=await api.login(username,password); localStorage.setItem('cg_token',r.access_token); setToken(r.access_token); setUser(r.user) }
  const logout=()=>{localStorage.removeItem('cg_token');setToken('');setUser(null);api.setToken('')}
  return <Ctx.Provider value={{user,token,loading,login,logout}}>{children}</Ctx.Provider>
}
export const useAuth=()=>useContext(Ctx)
