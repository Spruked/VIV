import axios from 'axios'

export const API_URL = import.meta.env.VITE_CALI_API_URL || 'http://127.0.0.1:21000'
export const TOKEN_KEY = 'cali_admin_token'

export const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
})

export function setAuthToken(token: string) {
  api.defaults.headers.common.Authorization = `Bearer ${token}`
}

export function clearAuthToken() {
  delete api.defaults.headers.common.Authorization
}

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function saveToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
  setAuthToken(token)
}

const token = getStoredToken()
if (token) setAuthToken(token)

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail || error.response?.data?.message || error.message
    return Promise.reject(new Error(String(detail || 'Request failed')))
  },
)
