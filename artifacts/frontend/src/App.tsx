import { Switch, Route, Redirect, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from "@tanstack/react-query";
import { getGetCurrentUserQueryKey } from "@workspace/api-client-react";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Layout } from "@/components/layout";
import { AuthProvider, useAuth, useIsAdmin } from "@/lib/auth";
import NotFound from "@/pages/not-found";

import Dashboard from "@/pages/dashboard";
import Library from "@/pages/library";
import AssetDetail from "@/pages/asset-detail";
import Jobs from "@/pages/jobs";
import AIQA from "@/pages/ai-qa";
import People from "@/pages/people";
import PersonDetail from "@/pages/person-detail";
import Insights from "@/pages/insights";
import Projects from "@/pages/projects";
import ProjectDetail from "@/pages/project-detail";
import Graphics from "@/pages/graphics";
import Ratings from "@/pages/ratings";
import Socials from "@/pages/socials";
import SearchPage from "@/pages/search";
import Login from "@/pages/login";
import UsersPage from "@/pages/users";

function is401(error: unknown): boolean {
  return (error as { status?: number })?.status === 401;
}

// Any 401 anywhere flips the app to the login screen by clearing the
// current-user cache entry (the auth gate below renders from it).
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (is401(error) && query.queryKey[0] !== getGetCurrentUserQueryKey()[0]) {
        queryClient.setQueryData(getGetCurrentUserQueryKey(), null);
      }
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      if (is401(error)) {
        queryClient.setQueryData(getGetCurrentUserQueryKey(), null);
      }
    },
  }),
});

function AdminRoute({ component: Component }: { component: React.ComponentType }) {
  const isAdmin = useIsAdmin();
  if (!isAdmin) return <Redirect to="/" />;
  return <Component />;
}

function Router() {
  return (
    <Layout>
      <Switch>
        <Route path="/" component={Dashboard} />
        <Route path="/projects" component={Projects} />
        <Route path="/projects/:id" component={ProjectDetail} />
        <Route path="/library" component={Library} />
        <Route path="/library/:id" component={AssetDetail} />
        <Route path="/people" component={People} />
        <Route path="/people/:id" component={PersonDetail} />
        <Route path="/graphics" component={Graphics} />
        <Route path="/insights" component={Insights} />
        <Route path="/ratings" component={Ratings} />
        <Route path="/socials" component={Socials} />
        <Route path="/jobs" component={Jobs} />
        <Route path="/ai" component={AIQA} />
        <Route path="/search" component={SearchPage} />
        <Route path="/users">
          <AdminRoute component={UsersPage} />
        </Route>
        {/* Old workflow pages now live inside Projects */}
        <Route path="/clips"><Redirect to="/projects" /></Route>
        <Route path="/reels"><Redirect to="/projects" /></Route>
        <Route path="/stories" nest><Redirect to="/projects" /></Route>
        <Route path="/exports"><Redirect to="/projects" /></Route>
        <Route path="/script-match"><Redirect to="/projects" /></Route>
        <Route component={NotFound} />
      </Switch>
    </Layout>
  );
}

function AuthGate() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="h-8 w-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      </div>
    );
  }

  if (!user) return <Login />;

  return <Router />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AuthProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
            <AuthGate />
          </WouterRouter>
        </AuthProvider>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
