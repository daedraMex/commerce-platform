import { NextResponse } from "next/server";

export const PROBLEM_CONTENT_TYPE = "application/problem+json";

const TITLES: Record<number, string> = {
  400: "Bad Request",
  401: "Unauthorized",
  403: "Forbidden",
  404: "Not Found",
  409: "Conflict",
  500: "Internal Server Error",
};

export type ProblemBody = {
  type: "about:blank";
  title: string;
  status: number;
  detail: string;
  code: string;
  errors?: Array<{ field: string; code: string; detail: string }>;
};

export function problemBody(
  status: number,
  code: string,
  detail: string,
  errors?: ProblemBody["errors"],
): ProblemBody {
  const body: ProblemBody = {
    type: "about:blank",
    title: TITLES[status] ?? "Error",
    status,
    detail,
    code,
  };
  if (errors) {
    body.errors = errors;
  }
  return body;
}

export function problemResponse(
  status: number,
  code: string,
  detail: string,
  errors?: ProblemBody["errors"],
): NextResponse {
  return NextResponse.json(problemBody(status, code, detail, errors), {
    status,
    headers: { "content-type": PROBLEM_CONTENT_TYPE },
  });
}

export async function forwardProblem(upstream: Response): Promise<NextResponse> {
  const contentType = upstream.headers.get("content-type") ?? "";
  if (contentType.includes(PROBLEM_CONTENT_TYPE)) {
    return new NextResponse(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: { "content-type": PROBLEM_CONTENT_TYPE },
    });
  }

  return problemResponse(
    upstream.status,
    upstream.status === 401 ? "token_invalid" : "upstream_error",
    upstream.statusText || "The backend rejected the request.",
  );
}
