"use client";

import { MessageSquareQuote, PhoneOutgoing, Table2 } from "lucide-react";

import type { ScreeningPlan } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

const TYPE_TONE: Record<string, string> = {
  boolean: "bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300",
  number: "bg-violet-50 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300",
  enum: "bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
  string: "bg-muted text-muted-foreground",
};

/**
 * Shows exactly what the voice agent will say and what it will bring back —
 * the questions, and the `result_schema` those answers land in. Those schema
 * keys become the columns of the results dashboard.
 */
export function ScreeningPlanCard({ plan }: { plan: ScreeningPlan }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <PhoneOutgoing className="size-4" /> Screening script
        </CardTitle>
        <p className="text-muted-foreground text-sm">
          {plan.questions.length} questions. The agent discloses it is an AI and asks
          permission before anything else.
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        <ol className="space-y-2">
          {plan.questions.map((question, index) => (
            <li key={question.key} className="flex gap-3 text-sm">
              <span className="text-muted-foreground w-5 shrink-0 text-right tabular-nums">
                {index + 1}.
              </span>
              <div className="min-w-0 flex-1">
                <p>{question.question}</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant="outline"
                    className={`font-mono text-[10px] font-normal ${
                      TYPE_TONE[question.answer_type] ?? TYPE_TONE.string
                    }`}
                  >
                    {question.key}
                  </Badge>
                  {question.rationale ? (
                    <span className="text-muted-foreground text-xs">
                      {question.rationale}
                    </span>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ol>

        <Accordion type="multiple" className="w-full">
          <AccordionItem value="intro">
            <AccordionTrigger className="text-sm">
              <span className="flex items-center gap-2">
                <MessageSquareQuote className="size-4" /> Opening line
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <p className="bg-muted/50 rounded-md p-3 text-sm italic">
                {plan.introduction}
              </p>
              <p className="text-muted-foreground mt-2 text-xs">
                Values in braces are filled per call from the candidate record.
              </p>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="prompt">
            <AccordionTrigger className="text-sm">Full agent prompt</AccordionTrigger>
            <AccordionContent>
              <pre className="bg-muted/50 max-h-80 overflow-auto rounded-md p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
                {plan.agent_prompt}
              </pre>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="schema">
            <AccordionTrigger className="text-sm">
              <span className="flex items-center gap-2">
                <Table2 className="size-4" /> Answer schema ({
                  Object.keys(plan.result_schema).length
                }{" "}
                fields)
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <p className="text-muted-foreground mb-2 text-xs">
                Sent to Hunar as <code className="font-mono">result_schema</code>. Each key
                becomes a column in the results dashboard.
              </p>
              <dl className="space-y-1.5">
                {Object.entries(plan.result_schema).map(([key, spec]) => (
                  <div key={key} className="text-xs">
                    <dt className="font-mono font-medium">{key}</dt>
                    <dd className="text-muted-foreground">{spec}</dd>
                  </div>
                ))}
              </dl>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </CardContent>
    </Card>
  );
}
