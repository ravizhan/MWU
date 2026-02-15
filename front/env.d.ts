/// <reference types="vite/client" />

declare global {
  interface Window {
    /** Naive UI message api (set in app startup / views as needed) */
    $message?: import("naive-ui").MessageApi
  }
}

export {}

declare module "*.css?url" {
  const href: string
  export default href
}
