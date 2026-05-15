import { createBrowserRouter, RouterProvider, NavLink, Outlet } from 'react-router';
import { ReplayPage } from './pages/replay/ReplayPage';
import { DocsPage } from './pages/docs/DocsPage';

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? 'bg-primary text-primary-foreground'
      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  }`;

function Layout() {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b px-6 py-3 flex items-center gap-4">
        <h1 className="text-lg font-semibold text-foreground">casino-floor</h1>
        <nav className="flex gap-1">
          <NavLink to="/" end className={navLinkClass}>
            Replay
          </NavLink>
          <NavLink to="/docs" className={navLinkClass}>
            Docs
          </NavLink>
        </nav>
      </header>

      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <ReplayPage /> },
      { path: '/docs', element: <DocsPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
