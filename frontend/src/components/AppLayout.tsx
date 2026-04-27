import NavBar from './NavBar'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <NavBar />
      <div className="flex-1 flex flex-col">
        {children}
      </div>
    </div>
  )
}
