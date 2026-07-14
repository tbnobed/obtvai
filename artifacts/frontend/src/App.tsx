import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Layout } from "@/components/layout";
import NotFound from "@/pages/not-found";

import Dashboard from "@/pages/dashboard";
import Library from "@/pages/library";
import AssetDetail from "@/pages/asset-detail";
import Search from "@/pages/search";
import Jobs from "@/pages/jobs";
import AIQA from "@/pages/ai-qa";
import ClipLists from "@/pages/clip-lists";
import Exports from "@/pages/exports";
import Reels from "@/pages/reels";
import ScriptMatch from "@/pages/script-match";
import People from "@/pages/people";
import PersonDetail from "@/pages/person-detail";
import Insights from "@/pages/insights";
import Stories from "@/pages/stories";
import Projects from "@/pages/projects";
import ProjectDetail from "@/pages/project-detail";

const queryClient = new QueryClient();

function Router() {
  return (
    <Layout>
      <Switch>
        <Route path="/" component={Dashboard} />
        <Route path="/projects" component={Projects} />
        <Route path="/projects/:id" component={ProjectDetail} />
        <Route path="/library" component={Library} />
        <Route path="/library/:id" component={AssetDetail} />
        <Route path="/search" component={Search} />
        <Route path="/people" component={People} />
        <Route path="/people/:id" component={PersonDetail} />
        <Route path="/insights" component={Insights} />
        <Route path="/jobs" component={Jobs} />
        <Route path="/ai" component={AIQA} />
        <Route path="/clips" component={ClipLists} />
        <Route path="/reels" component={Reels} />
        <Route path="/stories" component={Stories} />
        <Route path="/exports" component={Exports} />
        <Route path="/script-match" component={ScriptMatch} />
        <Route component={NotFound} />
      </Switch>
    </Layout>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
          <Router />
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
